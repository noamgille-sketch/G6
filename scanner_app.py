#!/usr/bin/env python3
"""G6 Guard scanner - the window the verified person sees.

Packaged by PyInstaller into a single G6Scan.exe, so nobody needs Python
installed. The dashboard serves it named G6Scan-<token>.exe and the app
reads the token out of its own filename: download, double-click, done.

Two modes, and the difference matters:

  Verification (a token is present)
      Everything is disclosed up front - what is read, what is never
      touched, and that the result goes straight to the person who asked.
      Then the scan runs and sends. The findings are NOT shown here and
      no report file is written, because someone who can read the verdict
      first can simply close the window when it says what they feared.
      Consent is therefore taken before the scan, covering the send.

  Private (no token)
      You are scanning your own PC. Everything is shown, nothing is sent,
      there is nowhere for it to go.
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

SERVER_URL = os.environ.get("G6_SERVER_URL", "@@SERVER_URL@@").rstrip("/")
TIMEOUT = 30

# Same palette as the dashboard, so the two halves feel like one product.
BG = "#0b0e15"
PANEL = "#121723"
PANEL_2 = "#171d2b"
LINE = "#222a3b"
TEXT = "#e9ecf4"
TEXT_2 = "#aab3c7"
MUTED = "#79839b"
ACCENT = "#4d7cfe"
ACCENT_HOVER = "#3d6bea"
OK = "#2fc98d"
WARN = "#f5b93b"
CRIT = "#f4374f"


def token_from_filename() -> str | None:
    name = os.path.basename(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"\s*\(\d+\)$", "", stem)  # browsers rename duplicates
    if "-" not in stem:
        return None
    return stem.split("-", 1)[1].strip() or None


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
        self.standalone = False

        self.server = SERVER_URL if "@@" not in SERVER_URL else ""
        self.token = token_from_filename()
        self.has_link = bool(self.token and self.server)

        root.title("G6 Guard")
        root.configure(bg=BG)
        self._center(760, 700)
        root.minsize(680, 600)

        base = "Segoe UI"
        self.f_h1 = tkfont.Font(family=base, size=19, weight="bold")
        self.f_h2 = tkfont.Font(family=base, size=11, weight="bold")
        self.f_body = tkfont.Font(family=base, size=10)
        self.f_small = tkfont.Font(family=base, size=9)
        self.f_tiny = tkfont.Font(family=base, size=8)
        self.f_mono = tkfont.Font(family="Consolas", size=9)
        self.f_verdict = tkfont.Font(family=base, size=27, weight="bold")
        self.f_brand = tkfont.Font(family=base, size=10, weight="bold")

        self._chrome()
        self.body = tk.Frame(root, bg=BG)
        self.body.pack(fill="both", expand=True)

        self.show_consent()

    # -- window furniture -------------------------------------------------

    def _center(self, w, h):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 3)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _chrome(self):
        bar = tk.Frame(self.root, bg=PANEL, height=52)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        inner = tk.Frame(bar, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=22)

        mark = tk.Label(inner, text="G6", font=self.f_brand, bg=ACCENT, fg="#ffffff",
                        padx=7, pady=3)
        mark.pack(side="left", pady=13)
        tk.Label(inner, text="  Guard", font=self.f_brand, bg=PANEL,
                 fg=TEXT).pack(side="left")

        self.step_label = tk.Label(inner, text="", font=self.f_tiny, bg=PANEL, fg=MUTED)
        self.step_label.pack(side="right")

        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x")

    def set_step(self, text):
        self.step_label.config(text=text)

    def clear(self):
        for widget in self.body.winfo_children():
            widget.destroy()

    def button(self, parent, text, command, kind="primary"):
        colors = {
            "primary": (ACCENT, "#ffffff", ACCENT_HOVER),
            "ghost": (PANEL_2, TEXT_2, LINE),
        }
        bg, fg, hover = colors[kind]
        btn = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                        activebackground=hover, activeforeground=fg,
                        font=self.f_h2, relief="flat", bd=0, padx=26, pady=12,
                        cursor="hand2", highlightthickness=0)
        btn.bind("<Enter>", lambda e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
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
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        return inner

    # -- screen 1: consent ------------------------------------------------

    def show_consent(self):
        self.clear()
        self.set_step("Étape 1 sur 2   ·   Ce que tu acceptes")

        wrap = self.scroll_area(self.body)
        pad = tk.Frame(wrap, bg=BG)
        pad.pack(fill="both", expand=True, padx=30, pady=26)

        if self.has_link:
            title = "Vérification demandée"
            sub = ("Quelqu'un t'a envoyé ce programme pour vérifier que ce PC "
                   "n'a pas de cheat FiveM.")
        else:
            title = "Vérifier ce PC"
            sub = "Contrôle des cheats FiveM sur cette machine."

        tk.Label(pad, text=title, font=self.f_h1, bg=BG, fg=TEXT,
                 anchor="w").pack(fill="x")
        tk.Label(pad, text=sub, font=self.f_body, bg=BG, fg=TEXT_2, anchor="w",
                 justify="left", wraplength=640).pack(fill="x", pady=(5, 20))

        self._banner(pad, profiles.PRIVACY_HEADLINE, profiles.PRIVACY_SUMMARY, OK)

        cols = tk.Frame(pad, bg=BG)
        cols.pack(fill="x", pady=(0, 18))
        cols.columnconfigure(0, weight=1, uniform="c")
        cols.columnconfigure(1, weight=1, uniform="c")
        self._list_card(cols, 0, "Ce qui est lu", profiles.REMOTE_COLLECTS, OK, "✓")
        self._list_card(cols, 1, "Ce qui n'est jamais touché",
                        profiles.REMOTE_NEVER_COLLECTS, CRIT, "✕")

        if self.has_link:
            self._banner(
                pad,
                "Le résultat part directement à la personne qui l'a demandé.",
                "Tu ne verras pas le détail dans cette fenêtre, et aucun rapport "
                "n'est écrit sur ce PC. C'est volontaire : si le résultat "
                "s'affichait d'abord, il suffirait de fermer la fenêtre pour le "
                "cacher, et la vérification ne vaudrait rien. En cliquant "
                "ci-dessous, tu acceptes que le résultat soit transmis.",
                ACCENT,
            )

        if not self.has_link:
            tk.Label(pad, text="Lien de vérification (laisse vide pour un contrôle privé)",
                     font=self.f_small, bg=BG, fg=MUTED, anchor="w").pack(fill="x", pady=(4, 6))
            self.link_entry = self._entry(pad, self.f_mono)
        else:
            self.link_entry = None

        tk.Label(pad, text="Ton pseudo", font=self.f_small, bg=BG, fg=MUTED,
                 anchor="w").pack(fill="x", pady=(6, 6))
        self.name_entry = self._entry(pad, self.f_body)
        self.name_entry.insert(0, os.environ.get("USERNAME") or "")

        self.consent_error = tk.Label(pad, text="", font=self.f_small, bg=BG, fg=CRIT,
                                      anchor="w", wraplength=640, justify="left")
        self.consent_error.pack(fill="x", pady=(14, 0))

        row = tk.Frame(pad, bg=BG)
        row.pack(fill="x", pady=(16, 0))
        label = "Accepter et lancer le scan" if self.has_link else "Lancer le scan"
        self.button(row, label, self.start_scan).pack(side="left")
        self.button(row, "Annuler", self.root.destroy, kind="ghost").pack(side="left", padx=10)

        if not self.has_link:
            tk.Label(pad, text="Sans lien, le résultat s'affiche ici et ne part nulle part.",
                     font=self.f_small, bg=BG, fg=MUTED, anchor="w",
                     wraplength=640, justify="left").pack(fill="x", pady=(16, 0))

    def _entry(self, parent, font):
        holder = tk.Frame(parent, bg=LINE, padx=1, pady=1)
        holder.pack(fill="x")
        entry = tk.Entry(holder, font=font, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                         relief="flat", bd=0)
        entry.pack(fill="x", ipady=9, ipadx=10)
        return entry

    def _banner(self, parent, title, text, color):
        card = tk.Frame(parent, bg=PANEL, highlightbackground=color, highlightthickness=1)
        card.pack(fill="x", pady=(0, 16))
        strip = tk.Frame(card, bg=color, height=3)
        strip.pack(fill="x")
        tk.Label(card, text=title, font=self.f_h2, bg=PANEL, fg=color, anchor="w",
                 justify="left", wraplength=620).pack(fill="x", padx=17, pady=(13, 5))
        tk.Label(card, text=text, font=self.f_small, bg=PANEL, fg=TEXT_2, anchor="w",
                 justify="left", wraplength=620).pack(fill="x", padx=17, pady=(0, 14))

    def _list_card(self, parent, col, title, items, color, bullet):
        card = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        card.grid(row=0, column=col, sticky="nsew", padx=(0, 7) if col == 0 else (7, 0))
        tk.Label(card, text=title, font=self.f_h2, bg=PANEL, fg=color,
                 anchor="w").pack(fill="x", padx=15, pady=(14, 9))
        for item in items:
            line = tk.Frame(card, bg=PANEL)
            line.pack(fill="x", padx=15, pady=(0, 7))
            tk.Label(line, text=bullet, font=self.f_small, bg=PANEL, fg=color,
                     width=2, anchor="nw").pack(side="left", anchor="n")
            tk.Label(line, text=item, font=self.f_small, bg=PANEL, fg=MUTED,
                     anchor="w", justify="left", wraplength=250).pack(side="left", fill="x")
        tk.Frame(card, bg=PANEL, height=7).pack()

    # -- screen 2: scanning -----------------------------------------------

    def start_scan(self):
        self.standalone = False

        if self.link_entry is not None:
            typed = self.link_entry.get().strip()
            if not typed:
                self.standalone = True
            else:
                server, token = parse_link(typed)
                if not token:
                    self.consent_error.config(
                        text="Ce lien n'est pas valide. Il ressemble à "
                             "https://.../verify/xxxxx — ou laisse le champ vide "
                             "pour un contrôle privé.")
                    return
                self.server = server or self.server
                self.token = token
                if not self.server:
                    self.consent_error.config(
                        text="Le lien doit contenir l'adresse complète du site.")
                    return

        self.display_name = (self.name_entry.get() or "").strip()[:80] or "anonyme"

        self.clear()
        self.set_step("Étape 2 sur 2   ·   Analyse")

        holder = tk.Frame(self.body, bg=BG)
        holder.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(holder, text="Analyse en cours", font=self.f_h1, bg=BG,
                 fg=TEXT).pack()
        self.status = tk.Label(holder, text="Démarrage...", font=self.f_body, bg=BG,
                               fg=TEXT_2, wraplength=480)
        self.status.pack(pady=(9, 4))
        self.counter = tk.Label(holder, text="", font=self.f_small, bg=BG, fg=MUTED)
        self.counter.pack(pady=(0, 22))

        track = tk.Frame(holder, bg=PANEL_2, width=420, height=6)
        track.pack()
        track.pack_propagate(False)
        self.bar = tk.Frame(track, bg=ACCENT, width=0, height=6)
        self.bar.place(x=0, y=0)
        self.track_width = 420

        tk.Label(holder, text="Quelques secondes. Ne ferme pas cette fenêtre.",
                 font=self.f_small, bg=BG, fg=MUTED).pack(pady=(22, 0))

        threading.Thread(target=self._scan_worker, daemon=True).start()
        self.root.after(100, self._poll)

    def _scan_worker(self):
        def progress(label, done, total):
            self.queue.put(("progress", (label, done, total)))
        try:
            report = build_report("remote", on_progress=progress)
            self.queue.put(("done", report))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def _poll(self):
        try:
            kind, payload = self.queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return

        if kind == "progress":
            label, done, total = payload
            self.status.config(text=label + "...")
            self.counter.config(text=f"{done + 1} / {total}")
            self.bar.configure(width=int(self.track_width * (done / total)))
            self.root.after(100, self._poll)
            return

        if kind == "error":
            self.show_error(f"Le scan n'a pas pu aller au bout : {payload}")
            return

        self.bar.configure(width=self.track_width)
        self.report = payload
        self.report["client_label"] = self.display_name

        if self.standalone:
            self.show_private_result()
        else:
            # No preview, no file on disk: send straight away.
            self.show_sending()
            threading.Thread(target=self._send_worker, daemon=True).start()

    # -- verification mode: send without showing anything -----------------

    def show_sending(self):
        self.clear()
        self.set_step("Envoi")
        holder = tk.Frame(self.body, bg=BG)
        holder.place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(holder, text="Envoi du résultat", font=self.f_h1, bg=BG, fg=TEXT).pack()
        tk.Label(holder, text="Transmission à la personne qui a demandé la vérification.",
                 font=self.f_body, bg=BG, fg=TEXT_2, wraplength=460,
                 justify="center").pack(pady=(9, 0))

    def _send_worker(self):
        url = f"{self.server}/api/verify/{self.token}/submit"
        try:
            data = json.dumps(self.report).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                resp.read()
            self.root.after(0, self.show_sent)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            self.root.after(0, lambda: self.show_send_failed(f"Le serveur a refusé l'envoi ({exc.code}). {detail}"))
        except urllib.error.URLError as exc:
            self.root.after(0, lambda: self.show_send_failed(
                f"Impossible de joindre le serveur : {exc.reason}"))
        except Exception as exc:
            self.root.after(0, lambda: self.show_send_failed(str(exc)))

    def show_sent(self):
        self.clear()
        self.set_step("Terminé")
        holder = tk.Frame(self.body, bg=BG)
        holder.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(holder, text="✓", font=tkfont.Font(family="Segoe UI", size=40),
                 bg=BG, fg=OK).pack()
        tk.Label(holder, text="Vérification terminée", font=self.f_h1, bg=BG,
                 fg=TEXT).pack(pady=(6, 0))
        tk.Label(holder, text="Le résultat a été transmis. Tu peux fermer cette fenêtre.\n"
                              "Ce lien est maintenant utilisé et ne peut plus resservir.",
                 font=self.f_body, bg=BG, fg=TEXT_2, justify="center").pack(pady=(10, 24))
        self.button(holder, "Fermer", self.root.destroy).pack()

    def show_send_failed(self, message):
        self.clear()
        self.set_step("Échec de l'envoi")
        holder = tk.Frame(self.body, bg=BG)
        holder.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(holder, text="L'envoi a échoué", font=self.f_h1, bg=BG, fg=WARN).pack()
        tk.Label(holder, text=message, font=self.f_body, bg=BG, fg=TEXT_2,
                 wraplength=470, justify="center").pack(pady=(10, 6))
        tk.Label(holder, text="Le scan a bien tourné, mais le résultat n'est pas parti. "
                              "Vérifie ta connexion, ou demande un nouveau lien.",
                 font=self.f_small, bg=BG, fg=MUTED, wraplength=470,
                 justify="center").pack(pady=(0, 22))

        row = tk.Frame(holder, bg=BG)
        row.pack()
        self.button(row, "Réessayer", self._retry_send).pack(side="left")
        self.button(row, "Fermer", self.root.destroy, kind="ghost").pack(side="left", padx=10)

    def _retry_send(self):
        self.show_sending()
        threading.Thread(target=self._send_worker, daemon=True).start()

    # -- private mode: show everything, send nothing ----------------------

    def show_private_result(self):
        self.clear()
        self.set_step("Contrôle privé   ·   rien n'a été envoyé")

        report = self.report
        verdict = report["verdict"]
        color = {"LEGIT": OK, "SUSPECT": WARN}.get(verdict, CRIT)

        wrap = self.scroll_area(self.body)
        pad = tk.Frame(wrap, bg=BG)
        pad.pack(fill="both", expand=True, padx=30, pady=26)

        head = tk.Frame(pad, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        head.pack(fill="x", pady=(0, 18))
        tk.Frame(head, bg=color, height=4).pack(fill="x")
        tk.Label(head, text=verdict, font=self.f_verdict, bg=PANEL, fg=color,
                 anchor="w").pack(fill="x", padx=20, pady=(16, 2))
        tk.Label(head, text=report["verdict_detail"], font=self.f_small, bg=PANEL,
                 fg=TEXT_2, anchor="w", justify="left",
                 wraplength=620).pack(fill="x", padx=20, pady=(0, 8))
        if report["detected_cheats"]:
            tk.Label(head, text="Cheats identifiés : " + ", ".join(report["detected_cheats"]),
                     font=self.f_h2, bg=PANEL, fg=CRIT, anchor="w", wraplength=620,
                     justify="left").pack(fill="x", padx=20, pady=(0, 16))
        else:
            tk.Frame(head, bg=PANEL, height=9).pack()

        findings = sorted(report["findings"], key=lambda f: -f["severity"])
        tk.Label(pad, text=f"Détail — {len(findings)} élément(s)", font=self.f_h2,
                 bg=BG, fg=TEXT, anchor="w").pack(fill="x", pady=(0, 11))

        if not findings:
            tk.Label(pad, text="Rien de suspect trouvé.", font=self.f_body, bg=BG,
                     fg=MUTED, anchor="w").pack(fill="x")

        for f in findings:
            sev = {"CRITICAL": CRIT, "HIGH": "#ff7a45", "MEDIUM": WARN,
                   "LOW": OK}.get(f["severity_label"], MUTED)
            row = tk.Frame(pad, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
            row.pack(fill="x", pady=(0, 7))
            tk.Frame(row, bg=sev, width=4).pack(side="left", fill="y")
            content = tk.Frame(row, bg=PANEL)
            content.pack(side="left", fill="both", expand=True, padx=14, pady=11)

            top = tk.Frame(content, bg=PANEL)
            top.pack(fill="x")
            tk.Label(top, text=f["severity_label"], font=self.f_tiny, bg=sev,
                     fg=BG if f["severity_label"] != "CRITICAL" else "#ffffff",
                     padx=6, pady=1).pack(side="left")
            tk.Label(top, text="  " + f["title"], font=self.f_h2, bg=PANEL, fg=TEXT,
                     anchor="w", justify="left", wraplength=520).pack(side="left")

            tk.Label(content, text=f["detail"], font=self.f_small, bg=PANEL, fg=MUTED,
                     anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(5, 0))

        tk.Label(pad, text="Contrôle privé : ce résultat n'a été envoyé nulle part. Pour "
                           "transmettre une vérification à quelqu'un, relance ce programme "
                           "avec le lien qu'il t'a donné.",
                 font=self.f_small, bg=BG, fg=MUTED, anchor="w", wraplength=640,
                 justify="left").pack(fill="x", pady=(18, 14))

        row = tk.Frame(pad, bg=BG)
        row.pack(fill="x")
        self.button(row, "Enregistrer le rapport", self.save_private_report).pack(side="left")
        self.button(row, "Fermer", self.root.destroy, kind="ghost").pack(side="left", padx=10)
        self.save_note = tk.Label(pad, text="", font=self.f_small, bg=BG, fg=OK,
                                  anchor="w", wraplength=640, justify="left")
        self.save_note.pack(fill="x", pady=(10, 0))

    def save_private_report(self):
        """Only offered for a scan of your own PC."""
        try:
            folder = os.path.dirname(os.path.abspath(
                sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = os.path.join(folder, f"g6-rapport-{stamp}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.report, fh, indent=2, ensure_ascii=False)
            self.save_note.config(text=f"Enregistré : {path}", fg=OK)
        except OSError as exc:
            self.save_note.config(text=f"Impossible d'enregistrer : {exc}", fg=CRIT)

    # -- errors -----------------------------------------------------------

    def show_error(self, message):
        self.clear()
        self.set_step("Erreur")
        holder = tk.Frame(self.body, bg=BG)
        holder.place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(holder, text="Erreur", font=self.f_h1, bg=BG, fg=CRIT).pack()
        tk.Label(holder, text=message, font=self.f_body, bg=BG, fg=TEXT_2,
                 wraplength=470, justify="center").pack(pady=(10, 22))
        self.button(holder, "Fermer", self.root.destroy).pack()


def main():
    root = tk.Tk()
    ScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
