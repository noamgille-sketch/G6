#!/usr/bin/env python3
"""G6 Guard scanner - the window the verified person sees.

Packaged by PyInstaller into a single G6Scan.exe, so nobody needs Python
installed. The dashboard serves it named G6Scan-<token>.exe, and the app
reads the token straight out of its own filename - the person just
double-clicks it, reads what it will do, and clicks Scan.

Order is deliberate: consent first, results second, sending last. Nothing
leaves the machine until the Send button is clicked.
"""
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime
from tkinter import font as tkfont

from g6_anticheat import profile as profiles
from g6_anticheat.engine import build_report

# Baked in at build time (see .github/workflows/build-scanner.yml). Without
# it the app asks for the full link instead.
SERVER_URL = os.environ.get("G6_SERVER_URL", "@@SERVER_URL@@").rstrip("/")
TIMEOUT = 30

BG = "#0f1117"
CARD = "#171a23"
BORDER = "#262b38"
TEXT = "#e6e8ee"
MUTED = "#8b90a0"
ACCENT = "#5b8cff"
OK = "#3fbf6f"
WARN = "#e6b800"
CRIT = "#ff3b5c"


def token_from_filename() -> str | None:
    """Read the token out of our own filename: G6Scan-<token>.exe"""
    name = os.path.basename(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
    stem = os.path.splitext(name)[0]
    # Browsers rename duplicates to "G6Scan-xxx (1).exe"
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    if "-" not in stem:
        return None
    token = stem.split("-", 1)[1].strip()
    return token or None


def parse_link(text: str) -> tuple[str | None, str | None]:
    text = (text or "").strip().rstrip("/")
    if "/verify/" in text:
        base, token = text.rsplit("/verify/", 1)
        return base.rstrip("/") or None, token or None
    if text and "/" not in text:
        return None, text
    return None, None


class ScannerApp:
    def __init__(self, root):
        self.root = root
        self.report = None
        self.queue = queue.Queue()

        self.server = SERVER_URL if "@@" not in SERVER_URL else ""
        self.token = token_from_filename()

        root.title("G6 Guard - Vérification FiveM")
        root.configure(bg=BG)
        root.geometry("720x640")
        root.minsize(640, 560)

        self.f_title = tkfont.Font(family="Segoe UI", size=17, weight="bold")
        self.f_h2 = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_body = tkfont.Font(family="Segoe UI", size=10)
        self.f_small = tkfont.Font(family="Segoe UI", size=9)
        self.f_mono = tkfont.Font(family="Consolas", size=9)
        self.f_verdict = tkfont.Font(family="Segoe UI", size=24, weight="bold")

        self.container = tk.Frame(root, bg=BG)
        self.container.pack(fill="both", expand=True)

        self.show_consent()

    # -- helpers ---------------------------------------------------------

    def clear(self):
        for widget in self.container.winfo_children():
            widget.destroy()

    def button(self, parent, text, command, primary=True, **kw):
        bg = ACCENT if primary else CARD
        btn = tk.Button(
            parent, text=text, command=command,
            bg=bg, fg="#ffffff" if primary else MUTED,
            activebackground=bg, activeforeground="#ffffff",
            font=self.f_h2, relief="flat", bd=0,
            padx=26, pady=11, cursor="hand2",
            highlightthickness=0, **kw,
        )
        return btn

    def scroll_area(self, parent):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        bar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window, width=e.width))
        canvas.configure(yscrollcommand=bar.set)

        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        def wheel(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")
        canvas.bind_all("<MouseWheel>", wheel)

        return inner

    # -- screen 1: consent -----------------------------------------------

    def show_consent(self):
        self.clear()
        body = self.scroll_area(self.container)
        pad = tk.Frame(body, bg=BG)
        pad.pack(fill="both", expand=True, padx=28, pady=24)

        tk.Label(pad, text="Vérification FiveM", font=self.f_title,
                 bg=BG, fg=TEXT, anchor="w").pack(fill="x")
        tk.Label(pad, text="Ce programme cherche uniquement des cheats FiveM sur ce PC.",
                 font=self.f_body, bg=BG, fg=MUTED, anchor="w").pack(fill="x", pady=(4, 18))

        # Privacy banner - the first thing that must be read.
        banner = tk.Frame(pad, bg="#12241a", highlightbackground=OK, highlightthickness=1)
        banner.pack(fill="x", pady=(0, 18))
        tk.Label(banner, text=profiles.PRIVACY_HEADLINE.upper(), font=self.f_h2,
                 bg="#12241a", fg=OK, anchor="w", justify="left",
                 wraplength=600).pack(fill="x", padx=16, pady=(13, 5))
        tk.Label(banner, text=profiles.PRIVACY_SUMMARY, font=self.f_small,
                 bg="#12241a", fg=TEXT, anchor="w", justify="left",
                 wraplength=600).pack(fill="x", padx=16, pady=(0, 13))

        cols = tk.Frame(pad, bg=BG)
        cols.pack(fill="x", pady=(0, 18))
        cols.columnconfigure(0, weight=1, uniform="c")
        cols.columnconfigure(1, weight=1, uniform="c")
        self._list_card(cols, 0, "Ce qui est regardé", profiles.REMOTE_COLLECTS, OK, "+")
        self._list_card(cols, 1, "Ce qui n'est jamais touché", profiles.REMOTE_NEVER_COLLECTS, CRIT, "—")

        if not self.token or not self.server:
            tk.Label(pad, text="Colle ici le lien que ton contact t'a envoyé :",
                     font=self.f_small, bg=BG, fg=MUTED, anchor="w").pack(fill="x", pady=(0, 6))
            self.link_entry = tk.Entry(pad, font=self.f_mono, bg=CARD, fg=TEXT,
                                       insertbackground=TEXT, relief="flat", bd=8)
            self.link_entry.pack(fill="x", pady=(0, 14))
        else:
            self.link_entry = None

        tk.Label(pad, text="Pseudo affiché avec le résultat :", font=self.f_small,
                 bg=BG, fg=MUTED, anchor="w").pack(fill="x", pady=(0, 6))
        self.name_entry = tk.Entry(pad, font=self.f_body, bg=CARD, fg=TEXT,
                                   insertbackground=TEXT, relief="flat", bd=8)
        self.name_entry.insert(0, os.environ.get("USERNAME") or "")
        self.name_entry.pack(fill="x", pady=(0, 20))

        self.consent_error = tk.Label(pad, text="", font=self.f_small, bg=BG, fg=CRIT,
                                      anchor="w", wraplength=620, justify="left")
        self.consent_error.pack(fill="x", pady=(0, 10))

        row = tk.Frame(pad, bg=BG)
        row.pack(fill="x")
        self.button(row, "Lancer le scan", self.start_scan).pack(side="left")
        self.button(row, "Fermer", self.root.destroy, primary=False).pack(side="left", padx=10)

        tk.Label(pad, text="Le rapport s'affiche ici et reste sur ce PC. Rien n'est envoyé "
                           "tant que tu n'as pas cliqué sur « Envoyer ».",
                 font=self.f_small, bg=BG, fg=MUTED, anchor="w",
                 wraplength=620, justify="left").pack(fill="x", pady=(16, 0))

    def _list_card(self, parent, col, title, items, color, bullet):
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))
        tk.Label(card, text=title, font=self.f_h2, bg=CARD, fg=color,
                 anchor="w").pack(fill="x", padx=14, pady=(12, 8))
        for item in items:
            tk.Label(card, text=f"{bullet}  {item}", font=self.f_small, bg=CARD,
                     fg=MUTED, anchor="w", justify="left",
                     wraplength=260).pack(fill="x", padx=14, pady=(0, 6))
        tk.Frame(card, bg=CARD, height=6).pack()

    # -- screen 2: scanning ----------------------------------------------

    def start_scan(self):
        if self.link_entry is not None:
            server, token = parse_link(self.link_entry.get())
            if not token:
                self.consent_error.config(text="Ce lien n'est pas valide. Il ressemble à "
                                               "https://.../verify/xxxxx")
                return
            self.server = server or self.server
            self.token = token
            if not self.server:
                self.consent_error.config(text="Le lien doit contenir l'adresse complète du site.")
                return

        self.clear()
        wrap = tk.Frame(self.container, bg=BG)
        wrap.pack(fill="both", expand=True)

        inner = tk.Frame(wrap, bg=BG)
        inner.place(relx=0.5, rely=0.45, anchor="center")

        tk.Label(inner, text="Scan en cours", font=self.f_title,
                 bg=BG, fg=TEXT).pack()
        self.status = tk.Label(inner, text="Analyse des programmes en cours d'exécution...",
                               font=self.f_body, bg=BG, fg=MUTED, wraplength=460)
        self.status.pack(pady=(8, 20))

        self.bar_bg = tk.Frame(inner, bg=CARD, width=380, height=5)
        self.bar_bg.pack()
        self.bar_bg.pack_propagate(False)
        self.bar = tk.Frame(self.bar_bg, bg=ACCENT, width=0, height=5)
        self.bar.place(x=0, y=0)
        self._pulse = 0
        self._animate()

        threading.Thread(target=self._scan_worker, daemon=True).start()
        self.root.after(120, self._poll)

    def _animate(self):
        if not self.bar_bg.winfo_exists():
            return
        self._pulse = (self._pulse + 9) % 460
        width = min(self._pulse, 380)
        self.bar.configure(width=width)
        self.root.after(28, self._animate)

    def _scan_worker(self):
        try:
            report = build_report("remote")
            self.queue.put(("done", report))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def _poll(self):
        try:
            kind, payload = self.queue.get_nowait()
        except queue.Empty:
            self.root.after(120, self._poll)
            return

        if kind == "error":
            self.show_error(f"Le scan a échoué : {payload}")
        else:
            self.report = payload
            self.report["client_label"] = self.name_entry_value()
            self.save_local_copy()
            self.show_result()

    def name_entry_value(self):
        try:
            return (self.name_entry.get() or "").strip()[:80] or "anonyme"
        except Exception:
            return "anonyme"

    def save_local_copy(self):
        try:
            folder = os.path.dirname(os.path.abspath(
                sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.report_path = os.path.join(folder, f"g6-rapport-{stamp}.json")
            with open(self.report_path, "w", encoding="utf-8") as fh:
                json.dump(self.report, fh, indent=2, ensure_ascii=False)
        except OSError:
            self.report_path = None

    # -- screen 3: result ------------------------------------------------

    def show_result(self):
        self.clear()
        report = self.report
        verdict = report["verdict"]
        color = {"LEGIT": OK, "SUSPECT": WARN}.get(verdict, CRIT)

        body = self.scroll_area(self.container)
        pad = tk.Frame(body, bg=BG)
        pad.pack(fill="both", expand=True, padx=28, pady=24)

        head = tk.Frame(pad, bg=CARD, highlightbackground=color, highlightthickness=2)
        head.pack(fill="x", pady=(0, 18))
        tk.Label(head, text=verdict, font=self.f_verdict, bg=CARD, fg=color,
                 anchor="w").pack(fill="x", padx=18, pady=(14, 2))
        tk.Label(head, text=report["verdict_detail"], font=self.f_small, bg=CARD,
                 fg=MUTED, anchor="w", justify="left",
                 wraplength=600).pack(fill="x", padx=18, pady=(0, 6))
        if report["detected_cheats"]:
            tk.Label(head, text="Cheats identifiés : " + ", ".join(report["detected_cheats"]),
                     font=self.f_h2, bg=CARD, fg=CRIT, anchor="w",
                     wraplength=600, justify="left").pack(fill="x", padx=18, pady=(0, 14))
        else:
            tk.Frame(head, bg=CARD, height=8).pack()

        findings = sorted(report["findings"], key=lambda f: -f["severity"])
        tk.Label(pad, text=f"Ce qui sera envoyé — {len(findings)} élément(s)",
                 font=self.f_h2, bg=BG, fg=TEXT, anchor="w").pack(fill="x", pady=(0, 10))

        if not findings:
            tk.Label(pad, text="Aucun élément suspect trouvé.", font=self.f_body,
                     bg=BG, fg=MUTED, anchor="w").pack(fill="x", pady=(0, 12))

        for f in findings:
            sev_color = {"CRITICAL": CRIT, "HIGH": "#e6673f",
                         "MEDIUM": WARN, "LOW": OK}.get(f["severity_label"], ACCENT)
            row = tk.Frame(pad, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x", pady=(0, 8))
            bar = tk.Frame(row, bg=sev_color, width=4)
            bar.pack(side="left", fill="y")
            content = tk.Frame(row, bg=CARD)
            content.pack(side="left", fill="both", expand=True, padx=12, pady=10)
            tk.Label(content, text=f"[{f['severity_label']}]  {f['title']}", font=self.f_h2,
                     bg=CARD, fg=sev_color, anchor="w", justify="left",
                     wraplength=560).pack(fill="x")
            tk.Label(content, text=f["detail"], font=self.f_small, bg=CARD, fg=MUTED,
                     anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(4, 0))

        if getattr(self, "report_path", None):
            tk.Label(pad, text=f"Copie complète enregistrée sur ce PC :\n{self.report_path}",
                     font=self.f_small, bg=BG, fg=MUTED, anchor="w",
                     justify="left", wraplength=620).pack(fill="x", pady=(10, 16))

        self.send_error = tk.Label(pad, text="", font=self.f_small, bg=BG, fg=CRIT,
                                   anchor="w", wraplength=620, justify="left")
        self.send_error.pack(fill="x", pady=(0, 8))

        row = tk.Frame(pad, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        self.send_btn = self.button(row, "Envoyer le résultat", self.send)
        self.send_btn.pack(side="left")
        self.button(row, "Ne pas envoyer", self.root.destroy, primary=False).pack(side="left", padx=10)

    # -- sending ---------------------------------------------------------

    def send(self):
        self.send_btn.config(text="Envoi...", state="disabled")
        self.send_error.config(text="")
        threading.Thread(target=self._send_worker, daemon=True).start()

    def _send_worker(self):
        url = f"{self.server}/api/verify/{self.token}/submit"
        try:
            data = json.dumps(self.report).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                json.loads(resp.read().decode("utf-8"))
            self.root.after(0, self.show_sent)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            self.root.after(0, lambda: self._send_failed(f"Envoi refusé ({exc.code}) : {detail}"))
        except urllib.error.URLError as exc:
            self.root.after(0, lambda: self._send_failed(
                f"Impossible de joindre le serveur : {exc.reason}"))
        except Exception as exc:
            self.root.after(0, lambda: self._send_failed(str(exc)))

    def _send_failed(self, message):
        self.send_error.config(text=message)
        self.send_btn.config(text="Réessayer l'envoi", state="normal")

    def show_sent(self):
        self.clear()
        inner = tk.Frame(self.container, bg=BG)
        inner.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(inner, text="Résultat envoyé", font=self.f_title, bg=BG, fg=OK).pack()
        tk.Label(inner, text="Ton contact voit maintenant le résultat.\n"
                             "Ce lien est consommé et ne peut plus être réutilisé.",
                 font=self.f_body, bg=BG, fg=MUTED, justify="center").pack(pady=(8, 22))
        self.button(inner, "Fermer", self.root.destroy).pack()

    def show_error(self, message):
        self.clear()
        inner = tk.Frame(self.container, bg=BG)
        inner.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(inner, text="Erreur", font=self.f_title, bg=BG, fg=CRIT).pack()
        tk.Label(inner, text=message, font=self.f_body, bg=BG, fg=MUTED,
                 wraplength=460, justify="center").pack(pady=(8, 22))
        self.button(inner, "Fermer", self.root.destroy).pack()


def main():
    root = tk.Tk()
    ScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
