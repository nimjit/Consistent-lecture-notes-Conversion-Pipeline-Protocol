// Project-wide Typst preamble for the lecture notes wiki.
// Imported by every build; referenced from protocol/protocol-org.org §Math (F4).
//
// Keep this file small. A macro belongs here only when it is used in more
// than one course. Course- or lecture-local notation should live inline.
//
// Spelling: follow the Typst convention (snake_case for let-bindings).
// Keep math-mode names short (one or two letters) where they are inlined.

// ---------- Vectors and tensors ----------

#let vb(x) = $bold(#x)$               // bold vector
#let uv(x) = $hat(bold(#x))$          // unit vector
#let mat_bold(x) = $bold(upright(#x))$ // bold-upright matrix

// ---------- Operators ----------

#let op(x) = $hat(#x)$                // operator hat
#let adj(x) = $#x^dagger$             // adjoint

// ---------- Quantum notation ----------

#let bra(x) = $lr(angle.l #x bar.v)$
#let ket(x) = $lr(bar.v #x angle.r)$
#let braket(a, b) = $lr(angle.l #a bar.v #b angle.r)$
#let expect(x) = $lr(angle.l #x angle.r)$

// ---------- Calculus shortcuts ----------

#let dd = $upright(d)$                // upright d for differentials
#let pdv(f, x) = $(partial #f) / (partial #x)$
#let dv(f, x) = $(dd #f) / (dd #x)$

// ---------- Sets ----------

#let RR = $bb(R)$
#let CC = $bb(C)$
#let ZZ = $bb(Z)$
#let NN = $bb(N)$
#let QQ = $bb(Q)$
