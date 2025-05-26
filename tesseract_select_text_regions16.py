import cv2
import pytesseract
from pytesseract import Output
from PIL import Image
import numpy as np
import sys
import os
import re
import tkinter as tk
from tkinter import scrolledtext, messagebox, Toplevel, filedialog
from spellchecker import SpellChecker
import subprocess
import threading

# --- Globals ---
CONFIG = {
    "image_path": None,
    "original_image": None,
    "gray_image": None,
    "tesseract_block_coords": {},
    "selected_tesseract_block_ids": [],
    "user_drawn_rects": [],
    "next_user_rect_id_counter": 0,
    "main_tk_root": None,
    "opencv_window_name": "OCR Image - Interactive Regions",
    "user_dict_file": "user_dictionary.txt",
    "corrections_file": "corrections.txt", # For global find/replace
    "global_corrections_map": {}, # Loaded from corrections_file {'find': 'replace'}
    "output_dir": "ocr_outputs",
    "ocr_confidence_threshold": 30,
    "block_padding": 3,
    "tkinter_update_interval": 50,
    "current_interaction_mode": "tesseract_select",
    "is_drawing_new_custom_rect": False,
    "new_custom_rect_start_point": None,
}

# --- UTILITIES / SPELL CHECK / TEXT CLEANUP (largely unchanged) ---
def load_user_dictionary(spell, user_dict_file):
    if os.path.exists(user_dict_file):
        with open(user_dict_file, "r", encoding="utf-8") as f:
            words = [line.strip() for line in f if line.strip()]
            spell.word_frequency.load_words(words)
    else: open(user_dict_file, "w").close()

def add_to_user_dictionary(word, spell, text_area, user_dict_file):
    word = word.strip()
    if word:
        with open(user_dict_file, "a", encoding="utf-8") as f: f.write(word.lower() + "\n")
        spell.word_frequency.load_words([word.lower()])
        highlight_misspelled(text_area, spell)

def highlight_misspelled(text_area, spell):
    text_area.tag_remove("misspelled", "1.0", tk.END)
    text_content = text_area.get("1.0", tk.END)
    for match in re.finditer(r'\b([a-zA-Z]+)\b', text_content):
        word = match.group(1);
        if len(word) < 3: continue
        if not spell.known([word.lower()]):
            start_index = f"1.0 + {match.start()} chars"; end_index = f"1.0 + {match.end()} chars"
            text_area.tag_add("misspelled", start_index, end_index)
    text_area.tag_config("misspelled", background="yellow", foreground="red")

def clean_and_reflow_text(raw_text):
    lines = raw_text.splitlines(); dehyphenated = []; i = 0; num_lines = len(lines)
    while i < num_lines:
        current_line_content = lines[i]; rstripped_line = current_line_content.rstrip()
        if rstripped_line.endswith('-') and (i + 1) < num_lines:
            next_line_original = lines[i+1]
            if next_line_original.strip():
                next_line_lstripped = next_line_original.lstrip(); is_continuation_candidate = False
                if next_line_lstripped:
                    first_char_next = next_line_lstripped[0]; part_before_hyphen_on_current = rstripped_line[:-1]
                    if first_char_next.islower(): is_continuation_candidate = True
                    elif first_char_next.isdigit():
                        if part_before_hyphen_on_current and part_before_hyphen_on_current.isalnum(): is_continuation_candidate = True
                if is_continuation_candidate:
                    part_before_hyphen = rstripped_line[:-1]
                    if '-' in part_before_hyphen: dehyphenated.append(rstripped_line + next_line_lstripped)
                    else: dehyphenated.append(part_before_hyphen + next_line_lstripped)
                    i += 2; continue
                else: dehyphenated.append(rstripped_line); i += 1; continue
            else: dehyphenated.append(rstripped_line); i += 2; continue
        dehyphenated.append(rstripped_line); i += 1
    reflowed_paragraphs_content = []; current_paragraph_lines = []
    for line_entry in dehyphenated:
        processed_line_for_paragraph = line_entry.strip()
        if not processed_line_for_paragraph:
            if current_paragraph_lines: reflowed_paragraphs_content.append(" ".join(current_paragraph_lines)); current_paragraph_lines = []
            if not reflowed_paragraphs_content or reflowed_paragraphs_content[-1]: reflowed_paragraphs_content.append("")
        else: current_paragraph_lines.append(processed_line_for_paragraph)
    if current_paragraph_lines: reflowed_paragraphs_content.append(" ".join(current_paragraph_lines))
    final_text_pieces = []
    for k, p_content_block in enumerate(reflowed_paragraphs_content):
        if p_content_block: final_text_pieces.append(p_content_block)
        elif k > 0 and reflowed_paragraphs_content[k-1]: final_text_pieces.append("")
    start_idx = 0;
    while start_idx < len(final_text_pieces) and not final_text_pieces[start_idx]: start_idx += 1
    end_idx = len(final_text_pieces);
    while end_idx > start_idx and not final_text_pieces[end_idx-1]: end_idx -=1
    return "\n\n".join(final_text_pieces[start_idx:end_idx])

# --- GLOBAL CORRECTIONS ---
def load_global_corrections():
    CONFIG["global_corrections_map"].clear()
    if not os.path.exists(CONFIG["corrections_file"]):
        try:
            with open(CONFIG["corrections_file"], "w", encoding="utf-8") as f:
                f.write("# Global Corrections: Use format 'find_string = replace_string'\n")
                f.write("# Example: teh = the\n")
                f.write("# Example: ist = 1st\n")
            print(f"'{CONFIG['corrections_file']}' created with examples.")
        except IOError as e:
            print(f"Error creating '{CONFIG['corrections_file']}': {e}")
            return

    try:
        with open(CONFIG["corrections_file"], "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    parts = line.split('=', 1)
                    find_str = parts[0].strip()
                    replace_str = parts[1].strip()
                    if find_str: # Ensure find_str is not empty
                        CONFIG["global_corrections_map"][find_str] = replace_str
                    else:
                        print(f"Warning: Empty find string in '{CONFIG['corrections_file']}' at line {line_num}: '{line}'")
                else:
                    print(f"Warning: Invalid format in '{CONFIG['corrections_file']}' at line {line_num} (missing '='): '{line}'")
    except IOError as e:
        print(f"Error reading '{CONFIG['corrections_file']}': {e}")
    print(f"Loaded {len(CONFIG['global_corrections_map'])} global corrections.")

def save_global_corrections_from_text(text_content, parent_window):
    new_corrections_map = {}
    lines = text_content.splitlines()
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            parts = line.split('=', 1)
            find_str = parts[0].strip()
            replace_str = parts[1].strip()
            if find_str:
                new_corrections_map[find_str] = replace_str
            else: # Silently ignore empty find string from editor for saving
                pass 
    
    CONFIG["global_corrections_map"] = new_corrections_map
    try:
        with open(CONFIG["corrections_file"], "w", encoding="utf-8") as f:
            if not new_corrections_map: # Write header if map is empty
                 f.write("# Global Corrections: Use format 'find_string = replace_string'\n")
            for find_s, replace_s in CONFIG["global_corrections_map"].items():
                f.write(f"{find_s} = {replace_s}\n")
        messagebox.showinfo("Corrections Saved", f"{len(CONFIG['global_corrections_map'])} corrections saved to '{CONFIG['corrections_file']}' and applied.", parent=parent_window)
    except IOError as e:
        messagebox.showerror("Save Error", f"Could not save corrections to '{CONFIG['corrections_file']}': {e}", parent=parent_window)

def apply_global_corrections(text, corrections_map):
    if not corrections_map:
        return text
    modified_text = text
    for find_str, replace_str in corrections_map.items():
        # re.escape ensures any special regex characters in find_str are treated literally
        escaped_find_str = re.escape(find_str)
        
        # Pattern: (?<!\w) means "not preceded by a word character (alphanumeric or underscore)"
        #          (?!\w) means "not followed by a word character (alphanumeric or underscore)"
        # This effectively creates "whole word/phrase" boundaries suitable for strings
        # that might start/end with symbols or include spaces.
        pattern = r'(?<!\w)' + escaped_find_str + r'(?!\w)'
        
        try:
            modified_text = re.sub(pattern, replace_str, modified_text)
        except re.error as e:
            # This might happen if a find_str creates an invalid regex pattern even after escaping,
            # though unlikely for typical text.
            print(f"Regex error for rule ['{find_str}' = '{replace_str}']: {e}. Skipping this rule.")
            # You could also log this to a file or a status bar in the UI
            continue # Skip this problematic rule

    return modified_text

corrections_editor_text_widget = None # Global reference for the text widget

def show_corrections_editor(parent_root):
    global corrections_editor_text_widget
    editor_window = Toplevel(parent_root)
    editor_window.title("Global Corrections Editor")
    editor_window.geometry("500x400")

    # Instructions
    instr_text = "Enter corrections: 'find text = replace text' (one per line).\nLines starting with # are comments. Whole word, case-sensitive."
    tk.Label(editor_window, text=instr_text, justify=tk.LEFT, wraplength=480).pack(pady=(5,0), padx=10)

    text_frame = tk.Frame(editor_window)
    text_frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
    corrections_editor_text_widget = scrolledtext.ScrolledText(text_frame, width=60, height=15, wrap=tk.WORD, undo=True)
    corrections_editor_text_widget.pack(fill=tk.BOTH, expand=True)

    # Populate with current corrections
    current_rules_text = ""
    if not CONFIG["global_corrections_map"]:
         current_rules_text = "# Global Corrections: Use format 'find_string = replace_string'\n# Example: teh = the\n# Example: ist = 1st\n"
    else:
        for find_s, replace_s in CONFIG["global_corrections_map"].items():
            current_rules_text += f"{find_s} = {replace_s}\n"
    corrections_editor_text_widget.insert(tk.END, current_rules_text)
    
    def on_save_apply():
        content = corrections_editor_text_widget.get("1.0", tk.END).strip()
        save_global_corrections_from_text(content, editor_window)

    tk.Button(editor_window, text="Save & Apply Corrections", command=on_save_apply).pack(pady=10)

    # Make it non-modal, but keep it on top if desired, or just let it be a normal Toplevel
    # editor_window.transient(parent_root) # Makes it stay on top of parent
    editor_window.focus_set()
    # Handle closing via 'X' - maybe ask to save or just close
    editor_window.protocol("WM_DELETE_WINDOW", editor_window.destroy)


# --- OCR HANDLING & OpenCV Display (mouse_callback, draw_regions, update_opencv_window unchanged) ---
current_mouse_pos_for_preview = (0,0)
def mouse_callback(event, x, y, flags, param): #_
    global current_mouse_pos_for_preview; current_mouse_pos_for_preview = (x,y)
    if CONFIG["current_interaction_mode"] == "tesseract_select":
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked_block_id = None
            for block_id, (x1_t, y1_t, x2_t, y2_t) in CONFIG["tesseract_block_coords"].items():
                if x1_t <= x <= x2_t and y1_t <= y <= y2_t: clicked_block_id = block_id; break
            if clicked_block_id:
                if clicked_block_id in CONFIG["selected_tesseract_block_ids"]: CONFIG["selected_tesseract_block_ids"].remove(clicked_block_id)
                else: CONFIG["selected_tesseract_block_ids"].append(clicked_block_id)
    elif CONFIG["current_interaction_mode"] == "custom_draw":
        if event == cv2.EVENT_LBUTTONDOWN: CONFIG["is_drawing_new_custom_rect"] = True; CONFIG["new_custom_rect_start_point"] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            if CONFIG["is_drawing_new_custom_rect"]:
                CONFIG["is_drawing_new_custom_rect"] = False; x1_c, y1_c = CONFIG["new_custom_rect_start_point"]; x2_c, y2_c = x, y
                final_x1, final_y1 = min(x1_c, x2_c), min(y1_c, y2_c); final_x2, final_y2 = max(x1_c, x2_c), max(y1_c, y2_c)
                if final_x2 > final_x1 + 5 and final_y2 > final_y1 + 5: CONFIG["user_drawn_rects"].append((final_x1, final_y1, final_x2, final_y2))
                CONFIG["new_custom_rect_start_point"] = None

def draw_regions_on_image(): #_
    display_img = CONFIG["original_image"].copy()
    for block_id, (x1, y1, x2, y2) in CONFIG["tesseract_block_coords"].items(): # Tesseract Blocks
        color = (0, 255, 0) if block_id in CONFIG["selected_tesseract_block_ids"] else (0, 0, 200)
        cv2.rectangle(display_img, (x1, y1), (x2, y2), color, 2)
    for (x1_u, y1_u, x2_u, y2_u) in CONFIG["user_drawn_rects"]: # User-Defined Rectangles
        cv2.rectangle(display_img, (x1_u, y1_u), (x2_u, y2_u), (255, 0, 0), 2) # Blue
    if CONFIG["is_drawing_new_custom_rect"] and CONFIG["new_custom_rect_start_point"]: # Live preview
        x1_p, y1_p = CONFIG["new_custom_rect_start_point"]; x2_p, y2_p = current_mouse_pos_for_preview
        cv2.rectangle(display_img, (x1_p, y1_p), (x2_p, y2_p), (200, 200, 0), 1)
    return display_img

def update_opencv_window(): #_
    if CONFIG["original_image"] is not None:
        display_img = draw_regions_on_image(); cv2.imshow(CONFIG["opencv_window_name"], display_img); cv2.waitKey(1)
    if CONFIG["main_tk_root"] and CONFIG["main_tk_root"].winfo_exists(): CONFIG["main_tk_root"].after(CONFIG["tkinter_update_interval"], update_opencv_window)

# --- OLLAMA GRAMMAR (unchanged) ---
def run_ollama_grammar_check(text_to_check, parent_window_for_popup): #_
    prompt = ("Correct the grammar and punctuation of the following historical text.\n"
              "Do not paraphrase or simplify. Preserve technical phrases and original meaning:\n\n" + text_to_check)
    try:
        proc = subprocess.Popen(["ollama", "run", "llama3"], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        stdout, stderr = proc.communicate(input=prompt, timeout=120)
        if proc.returncode != 0: return f"[Ollama Error (code {proc.returncode}): {stderr.strip()}]"
        return stdout.strip()
    except FileNotFoundError: return "[Ollama Error: 'ollama' command not found. Is it installed and in PATH?]"
    except subprocess.TimeoutExpired: return "[Ollama Error: Process timed out after 120 seconds.]"
    except Exception as e: return f"[Ollama Error: {e}]"

def show_working_popup(parent, message="Working..."): #_
    popup = Toplevel(parent); popup.title(""); popup.geometry("250x100")
    parent.update_idletasks(); parent_x, parent_y = parent.winfo_x(), parent.winfo_y()
    parent_width, parent_height = parent.winfo_width(), parent.winfo_height()
    popup_x = parent_x + (parent_width // 2) - (250 // 2); popup_y = parent_y + (parent_height // 2) - (100 // 2)
    popup.geometry(f"+{popup_x}+{popup_y}"); popup.transient(parent); popup.grab_set()
    tk.Label(popup, text=message, wraplength=230).pack(padx=10, pady=20, expand=True); popup.update(); return popup

# --- UI: TEXT EDITORS & DIALOGS (show_text_editor, ask_edit_mode unchanged from previous full code) ---
def show_text_editor(parent_root, text_content, output_file_path, title_prefix="Editor"): #_
    editor_window = Toplevel(parent_root); editor_window.title(f"{title_prefix} - {os.path.basename(output_file_path)}"); editor_window.geometry("700x500")
    spell = SpellChecker(); load_user_dictionary(spell, CONFIG["user_dict_file"])
    text_frame = tk.Frame(editor_window); text_frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
    text_area = scrolledtext.ScrolledText(text_frame, width=80, height=25, wrap=tk.WORD, undo=True)
    text_area.pack(fill=tk.BOTH, expand=True); text_area.insert(tk.END, text_content); highlight_misspelled(text_area, spell)
    def perform_save_action(): #_
        try:
            with open(output_file_path, "w", encoding="utf-8") as f: f.write(text_area.get("1.0", tk.END).strip())
            highlight_misspelled(text_area, spell)
            messagebox.showinfo("Saved", f"Text saved to\n{output_file_path}", parent=editor_window)
        except Exception as e: messagebox.showerror("Save Error", f"Could not save file:\n{e}", parent=editor_window)
    def save_and_close_action(): perform_save_action(); editor_window.destroy()
    ollama_button = None
    if title_prefix.startswith("Combined"): #_
        def grammar_check_action(): #_
            working_popup = show_working_popup(editor_window, "Running Ollama grammar check...")
            editor_window.update_idletasks()
            def correct_in_thread(): #_
                try:
                    raw_text_content = text_area.get("1.0", tk.END)
                    corrected_text = run_ollama_grammar_check(raw_text_content, editor_window)
                    editor_window.after(0, lambda: apply_corrections(corrected_text))
                except Exception as e_thread: editor_window.after(0, lambda: messagebox.showerror("Grammar Thread Error", str(e_thread), parent=editor_window))
                finally: editor_window.after(0, working_popup.destroy)
            def apply_corrections(corrected_text): #_
                if corrected_text.startswith("[Ollama Error"): messagebox.showerror("Grammar Check Error", corrected_text, parent=editor_window)
                else:
                    current_scroll = text_area.yview(); text_area.delete("1.0", tk.END); text_area.insert(tk.END, corrected_text)
                    text_area.yview_moveto(current_scroll[0]); highlight_misspelled(text_area, spell)
                    messagebox.showinfo("Grammar Check", "Grammar check complete.", parent=editor_window)
            threading.Thread(target=correct_in_thread, daemon=True).start()
        ollama_button = tk.Button(editor_window, text="Grammar (Ollama)", command=grammar_check_action)
    def on_right_click_editor(event): #_
        try:
            if not text_area.tag_ranges(tk.SEL): text_area.tag_add(tk.SEL, f"@%d,%d wordstart" % (event.x, event.y), f"@%d,%d wordend" % (event.x, event.y))
            selected_word = text_area.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
            if selected_word:
                cleaned_for_dict = re.sub(r'[^a-zA-Z\'-]', '', selected_word)
                if cleaned_for_dict and messagebox.askyesno("Dictionary", f"Add '{cleaned_for_dict}' to dictionary?", parent=editor_window):
                    add_to_user_dictionary(cleaned_for_dict, spell, text_area, CONFIG["user_dict_file"])
        except tk.TclError: pass
        finally:
            if text_area.tag_ranges(tk.SEL): text_area.tag_remove(tk.SEL, "1.0", tk.END)
    text_area.bind("<Button-3>", on_right_click_editor)
    button_frame = tk.Frame(editor_window); button_frame.pack(pady=5, padx=10, fill=tk.X)
    tk.Button(button_frame, text="Save", command=perform_save_action).pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Save and Close", command=save_and_close_action).pack(side=tk.LEFT, padx=5)
    if ollama_button: ollama_button.pack(side=tk.LEFT, padx=5)
    editor_window.protocol("WM_DELETE_WINDOW", save_and_close_action); editor_window.focus_set()

def ask_edit_mode(parent): #_
    dialog = Toplevel(parent); dialog.title("Edit Mode"); dialog.geometry("300x150")
    parent.update_idletasks(); parent_x, parent_y = parent.winfo_x(), parent.winfo_y()
    parent_width, parent_height = parent.winfo_width(), parent.winfo_height()
    dialog_x = parent_x + (parent_width // 2) - (300 // 2); dialog_y = parent_y + (parent_height // 2) - (150 // 2)
    dialog.geometry(f"+{dialog_x}+{dialog_y}"); dialog.transient(parent); dialog.grab_set()
    chosen_mode = tk.StringVar(value=None)
    tk.Label(dialog, text="Choose how to edit OCR results:").pack(padx=20, pady=10)
    tk.Button(dialog, text="Edit Blocks Separately", command=lambda: (chosen_mode.set("individual"), dialog.destroy())).pack(pady=5, fill=tk.X, padx=20)
    tk.Button(dialog, text="Edit Combined Text", command=lambda: (chosen_mode.set("combined"), dialog.destroy())).pack(pady=5, fill=tk.X, padx=20)
    dialog.protocol("WM_DELETE_WINDOW", lambda: (chosen_mode.set(None), dialog.destroy()))
    parent.wait_window(dialog); return chosen_mode.get()

# --- CONTROL PANEL COMMANDS & MAIN LOGIC ---
mode_switch_button_tk = None
status_label_tk = None

def cmd_switch_interaction_mode():
    global mode_switch_button_tk, status_label_tk
    if CONFIG["current_interaction_mode"] == "tesseract_select":
        CONFIG["current_interaction_mode"] = "custom_draw"
        if mode_switch_button_tk: mode_switch_button_tk.config(text="Switch to Select Tesseract Blocks")
        if status_label_tk: status_label_tk.config(text="Mode: Draw Custom Rectangles")
    else:
        CONFIG["current_interaction_mode"] = "tesseract_select"
        if mode_switch_button_tk: mode_switch_button_tk.config(text="Switch to Draw Custom Rectangles")
        if status_label_tk: status_label_tk.config(text="Mode: Select Tesseract Blocks")

def cmd_process_selected_regions():
    regions_to_process = []; region_sources = []
    for block_id in CONFIG["selected_tesseract_block_ids"]:
        if block_id in CONFIG["tesseract_block_coords"]:
            regions_to_process.append(CONFIG["tesseract_block_coords"][block_id])
            region_sources.append(f"tess_{block_id[0]}_{block_id[1]}_{block_id[2]}") # Include line_num if present
    for rect_coords in CONFIG["user_drawn_rects"]:
        regions_to_process.append(rect_coords)
        CONFIG["next_user_rect_id_counter"] += 1
        region_sources.append(f"custom_{CONFIG['next_user_rect_id_counter']}")
    if not regions_to_process: messagebox.showwarning("No Regions", "No Tesseract blocks selected and no custom regions drawn.", parent=CONFIG["main_tk_root"]); return
    edit_mode = ask_edit_mode(CONFIG["main_tk_root"]);
    if not edit_mode: return
    base_name = os.path.splitext(os.path.basename(CONFIG["image_path"]))[0]; os.makedirs(CONFIG["output_dir"], exist_ok=True)
    if edit_mode == "combined":
        combined_text_list = []; sortable_regions = []
        for i, coords in enumerate(regions_to_process): sortable_regions.append( ( (coords[1], coords[0]), coords, region_sources[i] ) )
        sortable_regions.sort()
        for idx, (_sort_key, coords, source_id) in enumerate(sortable_regions):
            x1, y1, x2, y2 = coords; pad = CONFIG["block_padding"]
            cropped_reg = CONFIG["gray_image"][max(0,y1-pad):min(CONFIG["gray_image"].shape[0],y2+pad), max(0,x1-pad):min(CONFIG["gray_image"].shape[1],x2+pad)]
            if cropped_reg.size == 0: continue
            raw_txt = pytesseract.image_to_string(Image.fromarray(cropped_reg), config='--psm 6')
            text_after_global_corrections = apply_global_corrections(raw_txt, CONFIG["global_corrections_map"]) # Apply corrections
            cleaned_txt = clean_and_reflow_text(text_after_global_corrections)
            combined_text_list.append(f"--- Region {idx+1} ({source_id}) ---\n{cleaned_txt}")
        full_text = "\n\n".join(combined_text_list)
        output_f = os.path.join(CONFIG["output_dir"], f"{base_name}_combined_ocr.txt")
        show_text_editor(CONFIG["main_tk_root"], full_text, output_f, title_prefix="Combined Editor")
    elif edit_mode == "individual":
        for idx, coords in enumerate(regions_to_process):
            x1, y1, x2, y2 = coords; source_id = region_sources[idx]; pad = CONFIG["block_padding"]
            cropped_reg = CONFIG["gray_image"][max(0,y1-pad):min(CONFIG["gray_image"].shape[0],y2+pad), max(0,x1-pad):min(CONFIG["gray_image"].shape[1],x2+pad)]
            if cropped_reg.size == 0: continue
            raw_txt = pytesseract.image_to_string(Image.fromarray(cropped_reg), config='--psm 6')
            text_after_global_corrections = apply_global_corrections(raw_txt, CONFIG["global_corrections_map"]) # Apply corrections
            cleaned_txt = clean_and_reflow_text(text_after_global_corrections)
            output_f = os.path.join(CONFIG["output_dir"], f"{base_name}_region_{idx+1}_{source_id}.txt")
            show_text_editor(CONFIG["main_tk_root"], cleaned_txt, output_f, title_prefix=f"Editor Region {idx+1} ({source_id})")

def cmd_clear_tesseract_selections(): CONFIG["selected_tesseract_block_ids"].clear()
def cmd_clear_custom_regions(): CONFIG["user_drawn_rects"].clear()
def cmd_exit_application():
    if messagebox.askyesno("Exit", "Are you sure you want to exit?", parent=CONFIG["main_tk_root"]):
        if CONFIG["main_tk_root"]: CONFIG["main_tk_root"].quit(); CONFIG["main_tk_root"].destroy()
        cv2.destroyAllWindows(); sys.exit(0)

def initial_ocr_pass():
    print("Performing initial OCR to identify Tesseract text blocks...")
    try: ocr_data = pytesseract.image_to_data(CONFIG["gray_image"], config='--psm 1', output_type=Output.DICT)
    except pytesseract.TesseractNotFoundError: print("ERROR: Tesseract not installed or not in PATH."); messagebox.showerror("Tesseract Error", "Tesseract is not installed or not found. Please install Tesseract OCR."); return False
    except Exception as e: print(f"ERROR: Pytesseract failed: {e}"); messagebox.showerror("Pytesseract Error", f"Pytesseract image_to_data failed: {e}"); return False
    CONFIG["tesseract_block_coords"].clear(); num_boxes = len(ocr_data['text'])
    for i in range(num_boxes):
        if int(ocr_data['conf'][i]) > CONFIG["ocr_confidence_threshold"]:
            text = ocr_data['text'][i].strip();
            if not text: continue
            block_id = (ocr_data['block_num'][i], ocr_data['par_num'][i], ocr_data['line_num'][i]) # Line-level
            x, y, w, h = ocr_data['left'][i], ocr_data['top'][i], ocr_data['width'][i], ocr_data['height'][i]
            if block_id in CONFIG["tesseract_block_coords"]:
                curr_x1, curr_y1, curr_x2, curr_y2 = CONFIG["tesseract_block_coords"][block_id]
                CONFIG["tesseract_block_coords"][block_id] = (min(curr_x1, x), min(curr_y1, y), max(curr_x2, x + w), max(curr_y2, y + h))
            else: CONFIG["tesseract_block_coords"][block_id] = (x, y, x + w, y + h)
    if not CONFIG["tesseract_block_coords"]: print("No Tesseract text blocks detected."); messagebox.showinfo("OCR Info", "No Tesseract blocks were detected.", parent=CONFIG["main_tk_root"])
    else: print(f"Detected {len(CONFIG['tesseract_block_coords'])} Tesseract text blocks (lines).")
    return True

def main():
    global mode_switch_button_tk, status_label_tk
    if len(sys.argv) < 2:
        root_temp = tk.Tk(); root_temp.withdraw()
        CONFIG["image_path"] = filedialog.askopenfilename(title="Select Image File", filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.tiff")])
        root_temp.destroy();
        if not CONFIG["image_path"]: print("No image file selected. Exiting."); return
    else: CONFIG["image_path"] = sys.argv[1]
    if not os.path.exists(CONFIG["image_path"]): print(f"Error: Image file not found: '{CONFIG['image_path']}'"); return
    CONFIG["original_image"] = cv2.imread(CONFIG["image_path"])
    if CONFIG["original_image"] is None: print(f"Error: Could not read image: '{CONFIG['image_path']}'."); return
    CONFIG["gray_image"] = cv2.cvtColor(CONFIG["original_image"], cv2.COLOR_BGR2GRAY)

    CONFIG["main_tk_root"] = tk.Tk(); CONFIG["main_tk_root"].title("OCR Control Panel"); CONFIG["main_tk_root"].geometry("380x260") # Increased height for status
    CONFIG["main_tk_root"].update_idletasks()
    screen_w, screen_h = CONFIG["main_tk_root"].winfo_screenwidth(), CONFIG["main_tk_root"].winfo_screenheight()
    app_w, app_h = 380, 260
    CONFIG["main_tk_root"].geometry(f"{app_w}x{app_h}+{(screen_w // 2) - (app_w // 2)}+{(screen_h // 2) - (app_h // 2)}")

    load_global_corrections() # Load corrections at startup
    if not initial_ocr_pass(): pass
    
    show_corrections_editor(CONFIG["main_tk_root"]) # Show corrections editor at startup

    cv2.namedWindow(CONFIG["opencv_window_name"]); cv2.setMouseCallback(CONFIG["opencv_window_name"], mouse_callback)
    control_frame = tk.Frame(CONFIG["main_tk_root"], pady=5); control_frame.pack(expand=True, fill=tk.BOTH) # Reduced pady
    
    status_label_tk = tk.Label(control_frame, text="Mode: Select Tesseract Blocks")
    status_label_tk.pack(pady=(0,5))

    mode_switch_button_tk = tk.Button(control_frame, text="Switch to Draw Custom Rectangles", command=cmd_switch_interaction_mode)
    mode_switch_button_tk.pack(pady=5, padx=20, fill=tk.X)
    tk.Button(control_frame, text="Process Selected & Drawn Regions", command=cmd_process_selected_regions, height=2).pack(pady=5, padx=20, fill=tk.X)
    clear_frame = tk.Frame(control_frame); clear_frame.pack(fill=tk.X, padx=15)
    tk.Button(clear_frame, text="Clear Tesseract Selections", command=cmd_clear_tesseract_selections).pack(side=tk.LEFT, pady=5, padx=5, expand=True, fill=tk.X)
    tk.Button(clear_frame, text="Clear Custom Rectangles", command=cmd_clear_custom_regions).pack(side=tk.LEFT, pady=5, padx=5, expand=True, fill=tk.X)
    tk.Button(control_frame, text="Exit Application", command=cmd_exit_application).pack(pady=(10,5), padx=20, fill=tk.X)
    CONFIG["main_tk_root"].protocol("WM_DELETE_WINDOW", cmd_exit_application)
    update_opencv_window()
    CONFIG["main_tk_root"].mainloop()

if __name__ == "__main__":
    main()