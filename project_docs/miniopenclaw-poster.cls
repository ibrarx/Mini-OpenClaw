\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{miniopenclaw-poster}[2026/06/01 Reusable A3 landscape poster class]

\LoadClass[11pt]{article}

\RequirePackage[a3paper,landscape,margin=1.5cm]{geometry}
\RequirePackage{amsmath,amssymb}
\RequirePackage{graphicx}
\RequirePackage{xcolor}
\RequirePackage{multicol}
\RequirePackage{iftex}
\RequirePackage{fontawesome5}
\ifLuaTeX
  \RequirePackage{emoji}
  \newcommand{\RobotEmoji}{\emoji{robot}}
\else
  \newcommand{\RobotEmoji}{\faIcon{robot}}
\fi
\RequirePackage{tikz}
\usetikzlibrary{arrows}
\RequirePackage{pgfplots}
\pgfplotsset{compat=1.18}

\setlength{\parindent}{0pt}\documentclass{miniopenclaw-poster}

\setlength{\parskip}{0.7\baselineskip}
\pagestyle{empty}

\RequirePackage{miniopenclaw-poster-style}