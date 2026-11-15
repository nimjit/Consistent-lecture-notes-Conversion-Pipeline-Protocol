-- Pandoc Lua filter: LaTeX math AST → Typst, emitted as RawInline("org", ...).
--
-- Protocol F3: no LaTeX in the org tree. Protocol F1/F2: Typst `$x^2$` inline
-- (flush), `$ x^2 $` block (spaced).
--
-- Known-macros table below handles the common cases. Anything we don't
-- recognise falls through _unknown(): emits `$ ? $` + an org comment with
-- the original LaTeX so the user and the lint pass can see what to fix.
--
-- Macros that match aliases defined in scripts/preamble.typ should keep
-- the same spellings here (vb, op, RR, etc.).

-- Direct name mappings. The filter escapes regex meta-chars at use time.
-- Typst's math symbol names (https://typst.app/docs/reference/symbols/sym/)
-- include the Greek alphabet, common operators, relations and arrows.
local KNOWN = {
  -- Blackboard-bold number sets. Use Typst's `bb()` primitive directly
  -- so output doesn't depend on preamble aliases.
  ["\\mathbb{R}"] = "bb(R)",
  ["\\mathbb{C}"] = "bb(C)",
  ["\\mathbb{Z}"] = "bb(Z)",
  ["\\mathbb{N}"] = "bb(N)",
  ["\\mathbb{Q}"] = "bb(Q)",
  -- Lowercase Greek.
  ["\\alpha"] = "alpha", ["\\beta"] = "beta", ["\\gamma"] = "gamma",
  ["\\delta"] = "delta", ["\\epsilon"] = "epsilon",
  ["\\varepsilon"] = "epsilon.alt", ["\\zeta"] = "zeta",
  ["\\eta"] = "eta", ["\\theta"] = "theta", ["\\vartheta"] = "theta.alt",
  ["\\iota"] = "iota", ["\\kappa"] = "kappa", ["\\lambda"] = "lambda",
  ["\\mu"] = "mu", ["\\nu"] = "nu", ["\\xi"] = "xi",
  ["\\omicron"] = "omicron", ["\\pi"] = "pi", ["\\varpi"] = "pi.alt",
  ["\\rho"] = "rho", ["\\varrho"] = "rho.alt",
  ["\\sigma"] = "sigma", ["\\varsigma"] = "sigma.alt",
  ["\\tau"] = "tau", ["\\upsilon"] = "upsilon",
  ["\\phi"] = "phi.alt", ["\\varphi"] = "phi",
  ["\\chi"] = "chi", ["\\psi"] = "psi", ["\\omega"] = "omega",
  -- Uppercase Greek (those that have distinct LaTeX forms).
  ["\\Gamma"] = "Gamma", ["\\Delta"] = "Delta", ["\\Theta"] = "Theta",
  ["\\Lambda"] = "Lambda", ["\\Xi"] = "Xi", ["\\Pi"] = "Pi",
  ["\\Sigma"] = "Sigma", ["\\Upsilon"] = "Upsilon",
  ["\\Phi"] = "Phi", ["\\Psi"] = "Psi", ["\\Omega"] = "Omega",
  -- Operators / big operators.
  ["\\partial"] = "diff", ["\\nabla"] = "nabla",
  ["\\int"] = "integral", ["\\oint"] = "integral.cont",
  ["\\iint"] = "integral.double", ["\\iiint"] = "integral.triple",
  ["\\sum"] = "sum", ["\\prod"] = "product",
  ["\\lim"] = "lim", ["\\inf"] = "inf", ["\\sup"] = "sup",
  ["\\min"] = "min", ["\\max"] = "max",
  ["\\sin"] = "sin", ["\\cos"] = "cos", ["\\tan"] = "tan",
  ["\\sec"] = "sec", ["\\csc"] = "csc", ["\\cot"] = "cot",
  ["\\arcsin"] = "arcsin", ["\\arccos"] = "arccos", ["\\arctan"] = "arctan",
  ["\\sinh"] = "sinh", ["\\cosh"] = "cosh", ["\\tanh"] = "tanh",
  ["\\exp"] = "exp", ["\\log"] = "log", ["\\ln"] = "ln",
  -- Relations.
  ["\\leq"] = "<=", ["\\geq"] = ">=", ["\\neq"] = "!=",
  ["\\ne"] = "!=", ["\\le"] = "<=", ["\\ge"] = ">=",
  ["\\equiv"] = "equiv", ["\\approx"] = "approx",
  ["\\sim"] = "tilde", ["\\simeq"] = "tilde.eq",
  ["\\propto"] = "prop", ["\\in"] = "in", ["\\notin"] = "in.not",
  ["\\subset"] = "subset", ["\\supset"] = "supset",
  ["\\subseteq"] = "subset.eq", ["\\supseteq"] = "supset.eq",
  -- Arrows.
  ["\\to"] = "->", ["\\rightarrow"] = "arrow", ["\\leftarrow"] = "arrow.l",
  ["\\leftrightarrow"] = "arrow.l.r",
  ["\\Rightarrow"] = "=>", ["\\Leftarrow"] = "arrow.l.double",
  ["\\Leftrightarrow"] = "<=>",
  ["\\mapsto"] = "arrow.r.bar",
  -- Dots / spacing.
  ["\\cdot"] = "dot.op", ["\\cdots"] = "dots.c",
  ["\\ldots"] = "dots.l", ["\\dots"] = "dots.h",
  ["\\vdots"] = "dots.v", ["\\ddots"] = "dots.down",
  -- Set-theoretic / logic.
  ["\\cup"] = "union", ["\\cap"] = "sect",
  ["\\bigcup"] = "union.big", ["\\bigcap"] = "sect.big",
  ["\\bigoplus"] = "plus.circle.big", ["\\bigotimes"] = "times.circle.big",
  ["\\oplus"] = "plus.circle", ["\\otimes"] = "times.circle",
  ["\\odot"] = "dot.circle", ["\\ominus"] = "minus.circle",
  ["\\setminus"] = "without",
  ["\\emptyset"] = "emptyset", ["\\varnothing"] = "emptyset",
  ["\\forall"] = "forall", ["\\exists"] = "exists",
  ["\\land"] = "and", ["\\lor"] = "or", ["\\lnot"] = "not",
  ["\\neg"] = "not", ["\\implies"] = "arrow.r.double",
  ["\\iff"] = "arrow.l.r.double",
  -- Infinity and misc constants.
  ["\\infty"] = "infinity",
  ["\\pm"] = "plus.minus", ["\\mp"] = "minus.plus",
  ["\\times"] = "times", ["\\div"] = "div",
  ["\\circ"] = "compose",
  ["\\star"] = "star", ["\\ast"] = "ast",
  -- Decorations / spacing (ignored for now — strip).
  ["\\,"] = " ", ["\\;"] = " ", ["\\:"] = " ", ["\\!"] = "",
  ["\\quad"] = "  ", ["\\qquad"] = "    ",
  ["\\left"] = "", ["\\right"] = "",
  ["\\big"] = "", ["\\Big"] = "", ["\\bigg"] = "", ["\\Bigg"] = "",
  ["\\displaystyle"] = "", ["\\textstyle"] = "",
  ["\\boldsymbol"] = "bold",
  -- Delimiters: literal braces / brackets / angles / floor / ceil / norms.
  ["\\{"] = "brace.l", ["\\}"] = "brace.r",
  ["\\lbrace"] = "brace.l", ["\\rbrace"] = "brace.r",
  ["\\langle"] = "angle.l", ["\\rangle"] = "angle.r",
  ["\\lceil"] = "ceil.l", ["\\rceil"] = "ceil.r",
  ["\\lfloor"] = "floor.l", ["\\rfloor"] = "floor.r",
  ["\\|"] = "||", ["\\lvert"] = "|", ["\\rvert"] = "|",
  ["\\lVert"] = "||", ["\\rVert"] = "||",
  -- Common math variants and symbols.
  ["\\mathring"] = "circle",
  ["\\overrightarrow"] = "arrow",
  ["\\underline"] = "underline",
  ["\\check"] = "caron",
  ["\\dot"] = "dot",
  ["\\ddot"] = "dot.double",
  ["\\prime"] = "prime",
}

-- Simple one-arg macros: pattern -> format string, where {} marks arg slot.
-- Target is Typst primitives, not preamble aliases, so output stands alone.
local ONE_ARG = {
  { "\\vec{(.-)}",      "arrow(%s)" },
  { "\\mathbf{(.-)}",   "bold(%s)" },
  { "\\hat{(.-)}",      "hat(%s)" },
  { "\\tilde{(.-)}",    "tilde(%s)" },
  { "\\bar{(.-)}",      "overline(%s)" },
  { "\\overline{(.-)}", "overline(%s)" },
  { "\\sqrt{(.-)}",     "sqrt(%s)" },
  { "\\mathcal{(.-)}",  "cal(%s)" },
  { "\\mathscr{(.-)}",  "cal(%s)" },
  { "\\mathfrak{(.-)}", "frak(%s)" },
  { "\\mathrm{(.-)}",   "upright(%s)" },
  { "\\mathit{(.-)}",   "italic(%s)" },
  { "\\mathsf{(.-)}",   "sans(%s)" },
  { "\\mathtt{(.-)}",   "mono(%s)" },
  { "\\text{(.-)}",     "text(\"%s\")" },
  { "\\textbf{(.-)}",   "bold(%s)" },
  { "\\textit{(.-)}",   "italic(%s)" },
  { "\\emph{(.-)}",     "italic(%s)" },
}

-- Two-arg macros.
local TWO_ARG = {
  { "\\frac{(.-)}{(.-)}", "(%s) / (%s)" },
}

-- Insert a space before `repl` when the preceding character is a word
-- character, so e.g. `R\exp(i\theta)` → `R exp(i theta)` not `Rexp(itheta)`.
-- Returns the replacement string suitable for gsub.
local function pad_prev(prev, repl)
  if prev:match("[%w_]") then
    return prev .. " " .. repl
  end
  return prev .. repl
end

local function convert_math(src)
  local unknown = {}
  local s = src

  -- Simple name substitutions. We capture the single character preceding
  -- the LaTeX macro and reinsert it with a space when it is a word char,
  -- so adjacent identifiers don't fuse. A frontier on the trailing side
  -- enforces identifier-boundary for patterns ending in a letter so
  -- `\alpha` doesn't eat `\alphabetize`. The frontier set is non-letter
  -- (not non-word) so digits following the macro — e.g. `\lbrace0` — still
  -- let the macro match.
  for latex, typst in pairs(KNOWN) do
    local pat = latex:gsub("([%%()%[%]%.%+%-%*%?%^%$])", "%%%1")
    local last = latex:sub(-1)
    local trail = last:match("[%a]") and "%f[^%a]" or ""
    s = s:gsub("(.?)" .. pat .. trail, function(prev)
      return pad_prev(prev, typst)
    end)
  end

  -- Two-arg macros before one-arg (so \frac{} is tried first).
  for _, pair in ipairs(TWO_ARG) do
    local pat, repl = pair[1], pair[2]
    s = s:gsub("(.?)" .. pat, function(prev, a, b)
      return pad_prev(prev, repl:format(a, b))
    end)
  end
  for _, pair in ipairs(ONE_ARG) do
    local pat, repl = pair[1], pair[2]
    s = s:gsub("(.?)" .. pat, function(prev, a)
      return pad_prev(prev, repl:format(a))
    end)
  end

  -- Any remaining `\cmd` is unknown. Keep its name as plain text (so a
  -- human reader can still make sense of the expression) and collect it
  -- for the lint-visible TODO list. Same word-boundary rule.
  s = s:gsub("(.?)\\([A-Za-z]+)", function(prev, name)
    table.insert(unknown, "\\" .. name)
    return pad_prev(prev, name)
  end)

  return s, unknown
end

local function unknown_comment(unknown, original)
  if #unknown == 0 then return nil end
  return pandoc.RawBlock("org",
    "#+BEGIN_COMMENT\nTODO-typst: unresolved macros " ..
    table.concat(unknown, ", ") .. " in\n  " .. original .. "\n#+END_COMMENT")
end

local function clean_display(src)
  -- Strip leading/trailing whitespace and collapse internal newlines to
  -- spaces: the Typst Emacs renderer only handles single-line `$ ... $`.
  src = src:gsub("^%s+", ""):gsub("%s+$", "")
  src = src:gsub("[\r\n]+", " ")
  return src
end

function Math(el)
  local typst, unknown = convert_math(el.text)
  if el.mathtype == "InlineMath" then
    return pandoc.RawInline("org", "$" .. typst .. "$")
  else
    -- DisplayMath: Typst `$ ... $` on a single line (F2).
    return pandoc.RawInline("org", "$ " .. clean_display(typst) .. " $")
  end
end
