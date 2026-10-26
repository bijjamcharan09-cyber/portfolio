/**
 * Bijjam Charan Kumar Reddy - Portfolio Script
 * Vanilla JavaScript (No frameworks, No dependencies)
 * Handles navigation, theme toggle, typewriter effect, project search/filter,
 * demo code preview modal, scroll animations, and contact form validation.
 */

document.addEventListener("DOMContentLoaded", () => {
  "use strict";

  // ==========================================================================
  // 1. Theme Management (Dark / Light)
  // ==========================================================================
  const THEME_STORAGE_KEY = "bckr_portfolio_theme";
  const themeToggleBtn = document.getElementById("themeToggleBtn");
  const htmlRoot = document.documentElement;

  // Determine initial theme: localStorage -> prefers-color-scheme -> dark default
  function getPreferredTheme() {
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    if (savedTheme === "light" || savedTheme === "dark") {
      return savedTheme;
    }
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      return "light";
    }
    return "dark";
  }

  function applyTheme(theme) {
    htmlRoot.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    if (themeToggleBtn) {
      const isDark = theme === "dark";
      themeToggleBtn.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
      themeToggleBtn.setAttribute("title", isDark ? "Switch to light theme" : "Switch to dark theme");
    }
  }

  // Initialize theme
  applyTheme(getPreferredTheme());

  // Listen for toggle clicks
  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const currentTheme = htmlRoot.getAttribute("data-theme") || "dark";
      const nextTheme = currentTheme === "dark" ? "light" : "dark";
      applyTheme(nextTheme);
    });
  }

  // Listen for OS color scheme changes if user hasn't explicitly set preference
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
      if (!localStorage.getItem(THEME_STORAGE_KEY)) {
        applyTheme(e.matches ? "light" : "dark");
      }
    });
  }

  // ==========================================================================
  // 2. Responsive Navigation & Smooth Scrolling
  // ==========================================================================
  const mobileNavToggle = document.getElementById("mobileNavToggle");
  const mainNavMenu = document.getElementById("mainNavMenu");
  const navLinks = document.querySelectorAll(".nav-link");

  function closeMobileMenu() {
    if (mainNavMenu && mobileNavToggle) {
      mainNavMenu.classList.remove("open");
      mobileNavToggle.setAttribute("aria-expanded", "false");
    }
  }

  function toggleMobileMenu() {
    if (mainNavMenu && mobileNavToggle) {
      const isOpen = mainNavMenu.classList.contains("open");
      if (isOpen) {
        closeMobileMenu();
      } else {
        mainNavMenu.classList.add("open");
        mobileNavToggle.setAttribute("aria-expanded", "true");
      }
    }
  }

  if (mobileNavToggle) {
    mobileNavToggle.addEventListener("click", toggleMobileMenu);
  }

  // Close mobile menu on link click and smooth scroll
  navLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      closeMobileMenu();
      const targetId = link.getAttribute("href");
      if (targetId && targetId.startsWith("#")) {
        const targetElement = document.querySelector(targetId);
        if (targetElement) {
          e.preventDefault();
          targetElement.scrollIntoView({ behavior: "smooth" });
          history.pushState(null, "", targetId);
        }
      }
    });
  });

  // Close mobile menu when clicking outside
  document.addEventListener("click", (e) => {
    if (
      mainNavMenu &&
      mobileNavToggle &&
      mainNavMenu.classList.contains("open") &&
      !mainNavMenu.contains(e.target) &&
      !mobileNavToggle.contains(e.target)
    ) {
      closeMobileMenu();
    }
  });

  // Active section highlighting on scroll
  const sections = document.querySelectorAll("section[id]");
  const observerOptions = {
    root: null,
    rootMargin: "-25% 0px -65% 0px",
    threshold: 0
  };

  const sectionObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const currentId = entry.target.getAttribute("id");
        navLinks.forEach((link) => {
          if (link.getAttribute("href") === `#${currentId}`) {
            link.classList.add("active");
          } else {
            link.classList.remove("active");
          }
        });
      }
    });
  }, observerOptions);

  sections.forEach((section) => sectionObserver.observe(section));

  // ==========================================================================
  // 3. Typing Animation (Hero Role Cycler)
  // ==========================================================================
  const roleTextElement = document.getElementById("heroRoleText");
  const roles = [
    "Second-Year Student",
    "Intermediate Python",
    "Building Small Projects"
  ];

  let currentRoleIndex = 0;
  let charIndex = 0;
  let isDeleting = false;
  let typingSpeed = 100;

  function typeRoleEffect() {
    if (!roleTextElement) return;

    const currentRole = roles[currentRoleIndex];

    if (isDeleting) {
      roleTextElement.textContent = currentRole.substring(0, charIndex - 1);
      charIndex--;
      typingSpeed = 50;
    } else {
      roleTextElement.textContent = currentRole.substring(0, charIndex + 1);
      charIndex++;
      typingSpeed = 100;
    }

    if (!isDeleting && charIndex === currentRole.length) {
      // Pause at full word
      typingSpeed = 2200;
      isDeleting = true;
    } else if (isDeleting && charIndex === 0) {
      isDeleting = false;
      currentRoleIndex = (currentRoleIndex + 1) % roles.length;
      typingSpeed = 400; // brief pause before next word
    }

    setTimeout(typeRoleEffect, typingSpeed);
  }

  typeRoleEffect();

  // ==========================================================================
  // 4. Project Search and Filtering
  // ==========================================================================
  const projectSearchInput = document.getElementById("projectSearchInput");
  const searchClearBtn = document.getElementById("searchClearBtn");
  const filterBtns = document.querySelectorAll(".filter-btn");
  const projectCards = document.querySelectorAll(".project-card");
  const noResultsState = document.getElementById("noResultsState");
  const resetFiltersBtn = document.getElementById("resetFiltersBtn");

  let activeFilter = "all";
  let searchQuery = "";

  function updateProjectVisibility() {
    let visibleCount = 0;
    const query = searchQuery.trim().toLowerCase();

    projectCards.forEach((card) => {
      const projectType = (card.getAttribute("data-type") || "").toLowerCase();
      const title = (card.getAttribute("data-title") || "").toLowerCase();
      const description = (card.getAttribute("data-desc") || "").toLowerCase();

      // Check category match
      const matchesFilter = activeFilter === "all" || projectType === activeFilter;

      // Check search match
      const matchesSearch = query === "" || title.includes(query) || description.includes(query);

      if (matchesFilter && matchesSearch) {
        card.classList.remove("hidden");
        visibleCount++;
      } else {
        card.classList.add("hidden");
      }
    });

    // Toggle empty state
    if (noResultsState) {
      if (visibleCount === 0) {
        noResultsState.classList.add("visible");
      } else {
        noResultsState.classList.remove("visible");
      }
    }
  }

  // Filter button click handler
  filterBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      activeFilter = btn.getAttribute("data-filter") || "all";
      updateProjectVisibility();
    });
  });

  // Search input handler
  if (projectSearchInput) {
    projectSearchInput.addEventListener("input", (e) => {
      searchQuery = e.target.value;
      if (searchClearBtn) {
        if (searchQuery.length > 0) {
          searchClearBtn.classList.add("visible");
        } else {
          searchClearBtn.classList.remove("visible");
        }
      }
      updateProjectVisibility();
    });
  }

  // Clear search button
  if (searchClearBtn) {
    searchClearBtn.addEventListener("click", () => {
      if (projectSearchInput) {
        projectSearchInput.value = "";
        searchQuery = "";
        searchClearBtn.classList.remove("visible");
        projectSearchInput.focus();
        updateProjectVisibility();
      }
    });
  }

  // Reset filters button in empty state
  if (resetFiltersBtn) {
    resetFiltersBtn.addEventListener("click", () => {
      if (projectSearchInput) {
        projectSearchInput.value = "";
        searchQuery = "";
      }
      if (searchClearBtn) {
        searchClearBtn.classList.remove("visible");
      }
      filterBtns.forEach((b) => {
        if (b.getAttribute("data-filter") === "all") {
          b.classList.add("active");
        } else {
          b.classList.remove("active");
        }
      });
      activeFilter = "all";
      updateProjectVisibility();
    });
  }

  // ==========================================================================
  // 5. Demo Code Preview Modal
  // ==========================================================================
  // Representative sample demonstration code for each project
  const sampleProjectsCode = {
    "expense-tracker": `# =====================================================================
# Project: Expense Tracker (Desktop GUI)
# Type: GUI | Level: Intermediate | Language: Python (Tkinter + ttk)
# Note: Sample Demonstration Code
# =====================================================================

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
from datetime import datetime

DATA_FILE = "expenses.json"

class ExpenseTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Python Expense Tracker")
        self.root.geometry("640x520")
        self.expenses = self.load_expenses()

        self.setup_ui()
        self.refresh_table()

    def setup_ui(self):
        # Entry Form Frame
        form_frame = ttk.LabelFrame(self.root, text="Add New Expense", padding=12)
        form_frame.pack(fill="x", padx=14, pady=10)

        # Title / Description
        ttk.Label(form_frame, text="Description:").grid(row=0, column=0, sticky="w", pady=4)
        self.desc_entry = ttk.Entry(form_frame, width=22)
        self.desc_entry.grid(row=0, column=1, padx=8, pady=4)

        # Amount
        ttk.Label(form_frame, text="Amount ($):").grid(row=0, column=2, sticky="w", pady=4)
        self.amount_entry = ttk.Entry(form_frame, width=12)
        self.amount_entry.grid(row=0, column=3, padx=8, pady=4)

        # Category
        ttk.Label(form_frame, text="Category:").grid(row=1, column=0, sticky="w", pady=4)
        self.category_var = tk.StringVar(value="Food")
        categories = ["Food", "Transport", "Books & Study", "Entertainment", "Utilities"]
        self.cat_menu = ttk.Combobox(form_frame, textvariable=self.category_var, values=categories, width=19, state="readonly")
        self.cat_menu.grid(row=1, column=1, padx=8, pady=4)

        # Add Button
        add_btn = ttk.Button(form_frame, text="Add Expense", command=self.add_expense)
        add_btn.grid(row=1, column=3, padx=8, pady=4, sticky="e")

        # Filter & Summary Bar
        filter_frame = ttk.Frame(self.root, padding=6)
        filter_frame.pack(fill="x", padx=14)

        ttk.Label(filter_frame, text="Filter Category:").pack(side="left")
        self.filter_var = tk.StringVar(value="All")
        filter_box = ttk.Combobox(filter_frame, textvariable=self.filter_var, values=["All"] + categories, state="readonly", width=14)
        filter_box.pack(side="left", padx=8)
        filter_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())

        self.summary_label = ttk.Label(filter_frame, text="Total: $0.00", font=("Segoe UI", 10, "bold"))
        self.summary_label.pack(side="right")

        # Expenses Table (Treeview)
        cols = ("ID", "Date", "Description", "Category", "Amount")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings", height=12)
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor="center")
        self.tree.column("Description", width=200, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=14, pady=10)

        # Action Buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=14, pady=8)
        del_btn = ttk.Button(btn_frame, text="Delete Selected", command=self.delete_expense)
        del_btn.pack(side="left")

    def add_expense(self):
        desc = self.desc_entry.get().strip()
        amt_str = self.amount_entry.get().strip()
        category = self.category_var.get()

        if not desc:
            messagebox.showwarning("Input Error", "Please provide a description.")
            return

        try:
            amount = float(amt_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Amount", "Please enter a positive numeric value.")
            return

        new_entry = {
            "id": len(self.expenses) + 1,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "desc": desc,
            "category": category,
            "amount": amount
        }
        self.expenses.append(new_entry)
        self.save_expenses()
        self.desc_entry.delete(0, tk.END)
        self.amount_entry.delete(0, tk.END)
        self.refresh_table()

    def delete_expense(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showinfo("Select Item", "Please select an item to delete.")
            return
        item_vals = self.tree.item(selected_item)["values"]
        item_id = item_vals[0]
        self.expenses = [x for x in self.expenses if x["id"] != item_id]
        self.save_expenses()
        self.refresh_table()

    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        selected_cat = self.filter_var.get()
        total = 0.0

        for exp in self.expenses:
            if selected_cat == "All" or exp["category"] == selected_cat:
                total += exp["amount"]
                self.tree.insert("", "end", values=(
                    exp["id"], exp["date"], exp["desc"], exp["category"], f"\${exp['amount']:.2f}"
                ))

        self.summary_label.config(text=f"Total: \${total:.2f}")

    def load_expenses(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save_expenses(self):
        with open(DATA_FILE, "w") as f:
            json.dump(self.expenses, f, indent=2)

if __name__ == "__main__":
    root = tk.Tk()
    app = ExpenseTrackerApp(root)
    root.mainloop()`,

    "student-management": `# =====================================================================
# Project: Student Management System (Desktop GUI)
# Type: GUI | Level: Intermediate | Language: Python (Tkinter + ttk)
# Note: Sample Demonstration Code
# =====================================================================

import tkinter as tk
from tkinter import ttk, messagebox
import json
import os

STUDENT_DB = "students.json"

class StudentManagementApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Student Records & Grade Management")
        self.root.geometry("740x560")
        self.students = self.load_data()

        self.create_widgets()
        self.populate_table()

    def create_widgets(self):
        # Header title
        header = ttk.Label(self.root, text="Student Management System", font=("Segoe UI", 14, "bold"))
        header.pack(pady=10)

        # Form Frame
        form = ttk.LabelFrame(self.root, text="Student Details & Grades", padding=10)
        form.pack(fill="x", padx=16, pady=6)

        ttk.Label(form, text="Roll Number:").grid(row=0, column=0, sticky="w", pady=4)
        self.roll_entry = ttk.Entry(form, width=16)
        self.roll_entry.grid(row=0, column=1, padx=6, pady=4)

        ttk.Label(form, text="Full Name:").grid(row=0, column=2, sticky="w", pady=4)
        self.name_entry = ttk.Entry(form, width=22)
        self.name_entry.grid(row=0, column=3, padx=6, pady=4)

        ttk.Label(form, text="Branch / Dept:").grid(row=1, column=0, sticky="w", pady=4)
        self.branch_var = tk.StringVar(value="CSE")
        branch_cb = ttk.Combobox(form, textvariable=self.branch_var, values=["CSE", "ECE", "MECH", "CIVIL"], width=14, state="readonly")
        branch_cb.grid(row=1, column=1, padx=6, pady=4)

        ttk.Label(form, text="Score / Marks (%):").grid(row=1, column=2, sticky="w", pady=4)
        self.marks_entry = ttk.Entry(form, width=12)
        self.marks_entry.grid(row=1, column=3, padx=6, pady=4, sticky="w")

        # Buttons Row
        btn_bar = ttk.Frame(form)
        btn_bar.grid(row=2, column=0, columnspan=4, pady=10)

        ttk.Button(btn_bar, text="Save Student", command=self.save_student).pack(side="left", padx=5)
        ttk.Button(btn_bar, text="Update Record", command=self.update_student).pack(side="left", padx=5)
        ttk.Button(btn_bar, text="Delete Record", command=self.delete_student).pack(side="left", padx=5)
        ttk.Button(btn_bar, text="Clear Form", command=self.clear_fields).pack(side="left", padx=5)

        # Records Table View
        table_frame = ttk.Frame(self.root)
        table_frame.pack(fill="both", expand=True, padx=16, pady=10)

        cols = ("Roll", "Name", "Branch", "Marks", "Grade", "Status")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=10)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=105, anchor="center")
        self.tree.column("Name", width=180, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select_record)

    def calculate_grade(self, marks):
        if marks >= 90: return ("A+", "Distinction")
        if marks >= 80: return ("A", "First Class")
        if marks >= 70: return ("B", "Second Class")
        if marks >= 50: return ("C", "Pass")
        return ("F", "Needs Improvement")

    def save_student(self):
        roll = self.roll_entry.get().strip()
        name = self.name_entry.get().strip()
        branch = self.branch_var.get()
        marks_raw = self.marks_entry.get().strip()

        if not roll or not name or not marks_raw:
            messagebox.showwarning("Validation", "All fields are required.")
            return

        try:
            marks = float(marks_raw)
            if not (0 <= marks <= 100):
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Marks must be between 0 and 100.")
            return

        # Check existing roll number
        if any(s["roll"] == roll for s in self.students):
            messagebox.showerror("Duplicate", "A student with this roll number already exists.")
            return

        grade, status = self.calculate_grade(marks)
        self.students.append({
            "roll": roll,
            "name": name,
            "branch": branch,
            "marks": marks,
            "grade": grade,
            "status": status
        })

        self.persist_data()
        self.populate_table()
        self.clear_fields()
        messagebox.showinfo("Success", f"Student {name} saved successfully.")

    def update_student(self):
        roll = self.roll_entry.get().strip()
        for student in self.students:
            if student["roll"] == roll:
                try:
                    marks = float(self.marks_entry.get().strip())
                    student["name"] = self.name_entry.get().strip()
                    student["branch"] = self.branch_var.get()
                    student["marks"] = marks
                    student["grade"], student["status"] = self.calculate_grade(marks)
                    self.persist_data()
                    self.populate_table()
                    messagebox.showinfo("Updated", "Student record updated.")
                    return
                except ValueError:
                    messagebox.showerror("Error", "Invalid marks value.")
                    return
        messagebox.showwarning("Not Found", "Select a valid existing student to update.")

    def delete_student(self):
        roll = self.roll_entry.get().strip()
        if not roll:
            messagebox.showwarning("Select", "Select a record to delete.")
            return
        self.students = [s for s in self.students if s["roll"] != roll]
        self.persist_data()
        self.populate_table()
        self.clear_fields()

    def on_select_record(self, event):
        sel = self.tree.selection()
        if sel:
            v = self.tree.item(sel[0])["values"]
            self.roll_entry.delete(0, tk.END)
            self.roll_entry.insert(0, v[0])
            self.name_entry.delete(0, tk.END)
            self.name_entry.insert(0, v[1])
            self.branch_var.set(v[2])
            self.marks_entry.delete(0, tk.END)
            self.marks_entry.insert(0, v[3])

    def clear_fields(self):
        self.roll_entry.delete(0, tk.END)
        self.name_entry.delete(0, tk.END)
        self.marks_entry.delete(0, tk.END)

    def populate_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for s in self.students:
            self.tree.insert("", "end", values=(
                s["roll"], s["name"], s["branch"], s["marks"], s["grade"], s["status"]
            ))

    def load_data(self):
        if os.path.exists(STUDENT_DB):
            try:
                with open(STUDENT_DB, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def persist_data(self):
        with open(STUDENT_DB, "w") as f:
            json.dump(self.students, f, indent=2)

if __name__ == "__main__":
    root = tk.Tk()
    app = StudentManagementApp(root)
    root.mainloop()`,

    "todo-list": `# =====================================================================
# Project: To-Do List Application (Command-Line Interface)
# Type: CLI | Level: Beginner | Language: Python 3
# Note: Sample Demonstration Code
# =====================================================================

import json
import os
import sys

DATA_FILE = "todo_tasks.json"

def load_tasks():
    """Load existing tasks from JSON file storage."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_tasks(tasks):
    """Save tasks to JSON file."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)

def list_tasks(tasks):
    """Display all tasks with priority and completion status."""
    if not tasks:
        print("\\n[!] Your to-do list is empty! Start by adding a task.")
        return

    print("\\n" + "=" * 54)
    print(f"{'ID':<4} {'Status':<10} {'Priority':<10} {'Task Description'}")
    print("-" * 54)

    for task in tasks:
        status_symbol = "[X] Done" if task.get("completed", False) else "[ ] Pending"
        priority = f"[{task.get('priority', 'Med')}]"
        print(f"{task['id']:<4} {status_symbol:<10} {priority:<10} {task['title']}")
    print("=" * 54)

def add_task(tasks):
    """Prompt user for a task and assign priority."""
    title = input("\\nEnter task description: ").strip()
    if not title:
        print("[!] Task description cannot be empty.")
        return

    print("Select Priority: 1. Low  2. Medium  3. High (Default: 2)")
    choice = input("Choice [1-3]: ").strip()
    priority_map = {"1": "Low", "2": "Medium", "3": "High"}
    priority = priority_map.get(choice, "Medium")

    new_id = (max([t["id"] for t in tasks], default=0)) + 1
    new_task = {
        "id": new_id,
        "title": title,
        "priority": priority,
        "completed": False
    }

    tasks.append(new_task)
    save_tasks(tasks)
    print(f"[✓] Task #{new_id} added successfully.")

def mark_completed(tasks):
    """Mark an existing task as completed."""
    list_tasks(tasks)
    if not tasks:
        return

    try:
        task_id = int(input("\\nEnter Task ID to mark completed: ").strip())
        for task in tasks:
            if task["id"] == task_id:
                task["completed"] = True
                save_tasks(tasks)
                print(f"[✓] Task #{task_id} marked as completed!")
                return
        print(f"[!] Task ID {task_id} not found.")
    except ValueError:
        print("[!] Please enter a valid numerical ID.")

def delete_task(tasks):
    """Delete a task by ID."""
    list_tasks(tasks)
    if not tasks:
        return

    try:
        task_id = int(input("\\nEnter Task ID to delete: ").strip())
        for i, task in enumerate(tasks):
            if task["id"] == task_id:
                deleted = tasks.pop(i)
                save_tasks(tasks)
                print(f"[✓] Deleted task: '{deleted['title']}'")
                return
        print(f"[!] Task ID {task_id} not found.")
    except ValueError:
        print("[!] Please enter a valid numerical ID.")

def main_menu():
    """Main CLI interaction loop."""
    tasks = load_tasks()

    while True:
        print("\\n=== Python CLI To-Do List ===")
        print("1. View Tasks")
        print("2. Add New Task")
        print("3. Mark Task as Completed")
        print("4. Delete Task")
        print("5. Exit")

        choice = input("\\nChoose an option [1-5]: ").strip()

        if choice == "1":
            list_tasks(tasks)
        elif choice == "2":
            add_task(tasks)
        elif choice == "3":
            mark_completed(tasks)
        elif choice == "4":
            delete_task(tasks)
        elif choice == "5":
            print("\\nThank you for using the CLI To-Do List. Happy coding!")
            break
        else:
            print("[!] Invalid option. Please select 1 through 5.")

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\\n\\nSession closed by user.")
        sys.exit(0)`,

    "password-generator": `# =====================================================================
# Project: Password Generator (Command-Line Tool)
# Type: CLI | Level: Beginner | Language: Python 3 (secrets module)
# Note: Sample Demonstration Code
# =====================================================================

import secrets
import string
import sys

def check_password_strength(password):
    """Evaluate password strength based on length and character variance."""
    length = len(password)
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in string.punctuation for c in password)

    score = 0
    if length >= 12: score += 2
    elif length >= 8: score += 1

    if has_upper: score += 1
    if has_lower: score += 1
    if has_digit: score += 1
    if has_special: score += 1

    if score >= 5: return "Strong (Excellent entropy)"
    if score >= 4: return "Moderate (Acceptable)"
    return "Weak (Consider increasing length and variety)"

def copy_to_clipboard(text):
    """Attempt cross-platform clipboard copy without extra external packages."""
    try:
        # Fallback using tkinter built-in clipboard helper
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False

def generate_custom_password(length=14, use_upper=True, use_lower=True, use_digits=True, use_symbols=True):
    """Generate a cryptographically secure random password."""
    pool = ""
    guaranteed = []

    if use_upper:
        pool += string.ascii_uppercase
        guaranteed.append(secrets.choice(string.ascii_uppercase))
    if use_lower:
        pool += string.ascii_lowercase
        guaranteed.append(secrets.choice(string.ascii_lowercase))
    if use_digits:
        pool += string.digits
        guaranteed.append(secrets.choice(string.digits))
    if use_symbols:
        symbols = "!@#$%^&*()-_=+[]{}|;:,.<>?"
        pool += symbols
        guaranteed.append(secrets.choice(symbols))

    if not pool:
        print("[!] Error: At least one character type must be selected.")
        return None

    if length < len(guaranteed):
        length = len(guaranteed)

    # Fill remaining characters securely
    remaining_length = length - len(guaranteed)
    password_list = guaranteed + [secrets.choice(pool) for _ in range(remaining_length)]

    # Cryptographically shuffle character order
    system_rng = secrets.SystemRandom()
    system_rng.shuffle(password_list)

    return "".join(password_list)

def main():
    print("=" * 48)
    print("    Python Secure CLI Password Generator")
    print("=" * 48)

    # Password Length
    while True:
        try:
            raw_len = input("\\nEnter desired password length [8-64, default 14]: ").strip()
            length = 14 if raw_len == "" else int(raw_len)
            if 8 <= length <= 64:
                break
            print("[!] Length must be between 8 and 64 characters.")
        except ValueError:
            print("[!] Please enter a valid number.")

    # Character Sets Selection
    print("\\nSelect Character Options (y/n, press enter for Yes):")
    inc_upper = input("Include Uppercase letters (A-Z)? [Y/n]: ").strip().lower() != "n"
    inc_lower = input("Include Lowercase letters (a-z)? [Y/n]: ").strip().lower() != "n"
    inc_digits = input("Include Digits (0-9)? [Y/n]: ").strip().lower() != "n"
    inc_symbols = input("Include Symbols (!@#$)? [Y/n]: ").strip().lower() != "n"

    pwd = generate_custom_password(length, inc_upper, inc_lower, inc_digits, inc_symbols)
    if not pwd:
        return

    strength = check_password_strength(pwd)

    print("\\n" + "-" * 48)
    print(f"Generated Password: {pwd}")
    print(f"Strength Rating   : {strength}")
    print("-" * 48)

    # Optional Clipboard Copy
    copy_choice = input("\\nCopy password to clipboard? [Y/n]: ").strip().lower()
    if copy_choice != "n":
        if copy_to_clipboard(pwd):
            print("[✓] Password copied to clipboard successfully!")
        else:
            print("[i] Clipboard copy not supported in current terminal environment.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\n\\nCancelled by user.")
        sys.exit(0)`
  };

  const projectTitles = {
    "expense-tracker": "Expense Tracker — Python GUI Application",
    "student-management": "Student Management System — Python GUI",
    "todo-list": "To-Do List — Python CLI Tool",
    "password-generator": "Password Generator — Python CLI Tool"
  };

  const codeModalBackdrop = document.getElementById("codeModalBackdrop");
  const modalProjectTitle = document.getElementById("modalProjectTitle");
  const modalCodeContent = document.getElementById("modalCodeContent");
  const modalCloseBtn = document.getElementById("modalCloseBtn");
  const modalCopyBtn = document.getElementById("modalCopyBtn");
  const viewCodeBtns = document.querySelectorAll(".btn-view-code");

  let lastActiveElement = null;
  let currentModalProjectId = null;

  function openCodeModal(projectId, triggerBtn) {
    if (!codeModalBackdrop || !sampleProjectsCode[projectId]) return;

    lastActiveElement = triggerBtn || document.activeElement;
    currentModalProjectId = projectId;

    if (modalProjectTitle) {
      modalProjectTitle.textContent = projectTitles[projectId] || "Sample Demonstration Code";
    }

    if (modalCodeContent) {
      modalCodeContent.textContent = sampleProjectsCode[projectId];
    }

    codeModalBackdrop.classList.add("open");
    codeModalBackdrop.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden"; // Prevent background scroll

    // Set focus to close button for accessibility
    if (modalCloseBtn) {
      modalCloseBtn.focus();
    }
  }

  function closeCodeModal() {
    if (!codeModalBackdrop) return;

    codeModalBackdrop.classList.remove("open");
    codeModalBackdrop.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";

    if (modalCopyBtn) {
      modalCopyBtn.innerHTML = `
        <svg class="btn-icon" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
        <span>Copy Code</span>
      `;
    }

    // Restore focus to last active element
    if (lastActiveElement && typeof lastActiveElement.focus === "function") {
      lastActiveElement.focus();
    }
  }

  // Bind View Code buttons
  viewCodeBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const projectId = btn.getAttribute("data-project");
      openCodeModal(projectId, btn);
    });
  });

  // Close button click
  if (modalCloseBtn) {
    modalCloseBtn.addEventListener("click", closeCodeModal);
  }

  // Close on backdrop click (outside modal content)
  if (codeModalBackdrop) {
    codeModalBackdrop.addEventListener("click", (e) => {
      if (e.target === codeModalBackdrop) {
        closeCodeModal();
      }
    });
  }

  // Keyboard navigation: Escape key to close modal & Tab loop
  document.addEventListener("keydown", (e) => {
    if (!codeModalBackdrop || !codeModalBackdrop.classList.contains("open")) return;

    if (e.key === "Escape") {
      closeCodeModal();
      return;
    }

    // Trap focus inside modal
    if (e.key === "Tab") {
      const focusableElements = codeModalBackdrop.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (focusableElements.length === 0) return;

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          lastElement.focus();
          e.preventDefault();
        }
      } else {
        if (document.activeElement === lastElement) {
          firstElement.focus();
          e.preventDefault();
        }
      }
    }
  });

  // Copy Code Button handler with fallback
  if (modalCopyBtn) {
    modalCopyBtn.addEventListener("click", () => {
      if (!currentModalProjectId || !sampleProjectsCode[currentModalProjectId]) return;

      const codeToCopy = sampleProjectsCode[currentModalProjectId];

      function indicateSuccess() {
        modalCopyBtn.innerHTML = `
          <svg class="btn-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>
          <span>Copied!</span>
        `;
        setTimeout(() => {
          modalCopyBtn.innerHTML = `
            <svg class="btn-icon" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            <span>Copy Code</span>
          `;
        }, 2200);
      }

      function fallbackCopyText(text) {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.top = "-9999px";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        try {
          const successful = document.execCommand("copy");
          if (successful) {
            indicateSuccess();
          } else {
            alert("Unable to copy code automatically. Please select the text and use Ctrl+C / Cmd+C.");
          }
        } catch (err) {
          alert("Unable to copy code automatically. Please select the text and use Ctrl+C / Cmd+C.");
        }
        document.body.removeChild(textarea);
      }

      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(codeToCopy)
          .then(indicateSuccess)
          .catch(() => fallbackCopyText(codeToCopy));
      } else {
        fallbackCopyText(codeToCopy);
      }
    });
  }

  // ==========================================================================
  // 6. Stats Section Viewport Animation
  // ==========================================================================
  const statCards = document.querySelectorAll(".stat-card");
  if (statCards.length > 0) {
    const statsObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry, idx) => {
        if (entry.isIntersecting) {
          // Stagger card reveal animations
          setTimeout(() => {
            entry.target.classList.add("animate-in");
          }, idx * 120);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.2 });

    statCards.forEach((card) => statsObserver.observe(card));
  }

  // ==========================================================================
  // 7. Contact Form Client-Side Validation & Honest Feedback
  // ==========================================================================
  const contactForm = document.getElementById("portfolioContactForm");
  const formFeedbackNotice = document.getElementById("formFeedbackNotice");
  const emailClientBtn = document.getElementById("emailClientBtn");

  if (contactForm) {
    const nameInput = document.getElementById("formName");
    const emailInput = document.getElementById("formEmail");
    const subjectInput = document.getElementById("formSubject");
    const messageInput = document.getElementById("formMessage");

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    function validateField(input, condition, errorMsgId, message) {
      const errorMsgEl = document.getElementById(errorMsgId);
      if (!condition) {
        input.classList.add("input-error");
        if (errorMsgEl) {
          errorMsgEl.textContent = message;
          errorMsgEl.classList.add("visible");
        }
        return false;
      } else {
        input.classList.remove("input-error");
        if (errorMsgEl) {
          errorMsgEl.textContent = "";
          errorMsgEl.classList.remove("visible");
        }
        return true;
      }
    }

    // Live validation on blur
    if (nameInput) {
      nameInput.addEventListener("blur", () => {
        validateField(nameInput, nameInput.value.trim().length >= 2, "nameError", "Please enter at least 2 characters.");
      });
    }

    if (emailInput) {
      emailInput.addEventListener("blur", () => {
        validateField(emailInput, emailRegex.test(emailInput.value.trim()), "emailError", "Please enter a valid email address.");
      });
    }

    if (subjectInput) {
      subjectInput.addEventListener("blur", () => {
        validateField(subjectInput, subjectInput.value.trim().length >= 3, "subjectError", "Please enter a subject (at least 3 characters).");
      });
    }

    if (messageInput) {
      messageInput.addEventListener("blur", () => {
        validateField(messageInput, messageInput.value.trim().length >= 10, "messageError", "Message must be at least 10 characters long.");
      });
    }

    contactForm.addEventListener("submit", (e) => {
      e.preventDefault();

      const isNameValid = validateField(nameInput, nameInput.value.trim().length >= 2, "nameError", "Please enter your name (at least 2 characters).");
      const isEmailValid = validateField(emailInput, emailRegex.test(emailInput.value.trim()), "emailError", "Please enter a valid email address.");
      const isSubValid = validateField(subjectInput, subjectInput.value.trim().length >= 3, "subjectError", "Please enter a subject (at least 3 characters).");
      const isMsgValid = validateField(messageInput, messageInput.value.trim().length >= 10, "messageError", "Message must be at least 10 characters long.");

      if (isNameValid && isEmailValid && isSubValid && isMsgValid) {
        // Construct genuine mailto link with encoded form parameters
        const recipient = "bijjamcharan09@gmail.com";
        const subject = encodeURIComponent(`[Portfolio Contact] ${subjectInput.value.trim()} - from ${nameInput.value.trim()}`);
        const body = encodeURIComponent(
          `Hi Charan,\n\n${messageInput.value.trim()}\n\nBest regards,\n${nameInput.value.trim()}\nEmail: ${emailInput.value.trim()}`
        );
        const mailtoUrl = `mailto:${recipient}?subject=${subject}&body=${body}`;

        // Configure direct open button
        if (emailClientBtn) {
          emailClientBtn.setAttribute("href", mailtoUrl);
        }

        // Show honest notice
        if (formFeedbackNotice) {
          formFeedbackNotice.classList.add("visible");
          formFeedbackNotice.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }
    });
  }

  // ==========================================================================
  // 8. Back to Top Button
  // ==========================================================================
  const backToTopBtn = document.getElementById("backToTopBtn");
  if (backToTopBtn) {
    window.addEventListener("scroll", () => {
      if (window.scrollY > 350) {
        backToTopBtn.classList.add("visible");
      } else {
        backToTopBtn.classList.remove("visible");
      }
    });

    backToTopBtn.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }
});
