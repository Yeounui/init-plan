# API Docs and Code Comments

Answers *what exactly this callable accepts, returns, and guarantees*. The unit is one function, method, RPC,
or message field — never a component (that is SDD) and never a project-wide rule (that is SDS/SCS).

API documentation lives with the code it describes. A separate hand-maintained copy drifts within weeks and
then actively misleads, so the published reference is generated from or points at the in-source text.

## Contents

- [Contract fields](#contract-fields)
- [Contract style: requires / ensures](#contract-style-requires--ensures)
- [A worked contract](#a-worked-contract)
- [Carrier by language](#carrier-by-language)
- [The published index](#the-published-index)
- [Comments that are not API docs](#comments-that-are-not-api-docs)
- [Common failures](#common-failures)

## Contract fields

| Field | Content | Omit when |
|---|---|---|
| Summary | One line: what it does, in the caller's terms | never |
| Parameters | Name, type, unit, valid range, default | no parameters |
| Returns | Type and meaning, including what a boundary value means | returns nothing |
| Raises / errors | Each error, and the condition that produces it | it cannot fail |
| Preconditions | What the caller must have established first | none |
| Postconditions | What is true after success, including observable side effects | pure and obvious |
| Side effects | State mutated, I/O performed, resources claimed | none |
| Concurrency | Thread-safety, reentrancy, required lock ownership | project rule covers it |
| Complexity | Time/space cost when a caller could be surprised | cost is obvious |
| Example | Typical call, plus one edge case if the edge is non-obvious | trivial accessor |

Units and ranges belong in the parameter line, not in prose below it. The reader checking whether their value
is legal is looking at the parameter, and prose separated from it gets skipped.

## Contract style: requires / ensures

The most checkable form states the caller's obligation and the callee's guarantee as an explicit pair:

- `requires:` — what must hold on entry. Violating it is a caller bug; behavior is undefined or a stated error.
- `ensures:` — what holds on successful return. This is the promise the caller may rely on and the callee may
  not weaken without a version change.

`requires:` is the caller's MUST and `ensures:` the callee's MUST, as SDS 1.1 fixes; neither line carries a
keyword.

This form is worth preferring because it makes the division of responsibility unambiguous — every failure is
attributable to whichever side broke its half — and because it is directly implementable and testable: a
`requires:` becomes a validation or assertion, an `ensures:` becomes a test assertion.

When components are designed as contracts before implementation, those contracts are the API documentation.
Implementation fills the body without rewriting the contract, and the published reference points at them.

## A worked contract

One complete contract, written as a pseudo-signature so the fields are visible without any language's comment
syntax around them:

```
put(store, key, value, ttl_s = 300) -> Receipt

Summary:      Write one record and return its durable position.
requires:     store is open; key is 1–64 bytes; ttl_s is within 0–86400
ensures:      on success the record is readable by key until ttl_s elapses, and
              Receipt.position increases monotonically within one store;
              on any raised error the store is unchanged
Params:       store — open handle, owned by the caller, not retained past the call
              key — record identity, 1–64 bytes
              value — payload, at most 1 MiB
              ttl_s — lifetime in seconds, 0–86400, default 300; 0 means no expiry
Returns:      Receipt carrying the durable position and the write timestamp
Raises:       StoreClosed — the store was closed or was never opened
              KeyTooLong — key exceeds 64 bytes
              QuotaExceeded — the store's byte budget is full
Side effects: appends to the store's log; claims one write slot for the duration of the call
Concurrency:  safe from several callers; ordering between concurrent puts is unspecified
```

This is rendered in the carrier its language uses. The field labels stay verbatim and only the syntax carrying
them changes, so a reader crossing between two languages in one project finds the same fields in the same
order. Where the signature already carries types, the parameter lines carry unit, range, and meaning instead of
repeating the type name.

## Carrier by language

| Language family | Where the contract lives | Generator that consumes it |
|---|---|---|
| Python | Docstring directly below the `def`/`class` line | Sphinx autodoc, pdoc, mkdocstrings |
| C, C++ | Block comment on the declaration in the header | Doxygen |
| Rust | `///` on the item, `//!` on the module | rustdoc |
| Go | Comment immediately above the declaration, starting with its name | `go doc`, pkgsite |
| Java, Kotlin | Javadoc / KDoc block on the declaration | javadoc, Dokka |
| JavaScript, TypeScript | JSDoc / TSDoc block above the declaration | TypeDoc, API Extractor |
| C# | XML documentation comments (`///`) on the member | DocFX |
| IDLs — protobuf, OpenAPI, GraphQL | Comment or `description` on the message, field, or method | protoc-gen-doc, Redoc, generated stubs |
| Shell, CLI | Header comment plus the `--help` text a caller reads | help2man, the parser's own help output |

An IDL comment reaches consumers through the generated stubs, so it is the contract in every language those
stubs are generated into. A language not listed uses its own dominant documentation-comment convention and that
convention's generator. The fields do not change with the language; only the syntax carrying them does.

Where a language separates declaration from definition, the contract goes on the declaration — that is what a
caller reads — and the definition carries implementation notes only. In manually memory-managed languages,
ownership and lifetime are the fields a caller cannot infer and most needs: who frees, whether a pointer is
retained past the call, and whether a returned pointer stays valid. Wire-level identities — field numbers, enum
values, status and error codes — are part of the contract: record one as retired rather than reassigning it to
a different meaning.

## The published index

The suite's API reference is an index, not a second copy: it groups callables by surface area and points at
the in-source contract. What it adds beyond the source is orientation — which surfaces exist, which are
public versus internal, and the errors common to a whole surface stated once rather than per callable. Each
language's generator produces its own index; a project spanning several publishes one index per generator plus
one routing page over them.

## Comments that are not API docs

In-body comments serve a different purpose and belong to SCS rules, not here. The distinction worth keeping:
API docs state the contract for someone who will never read the body; in-body comments explain a
non-obvious *why* to someone reading the body. A comment restating what the next line plainly does adds
maintenance cost and no information.

## Common failures

- **Type restated as description.** `volume_ul: float — a float` says nothing. State the unit and range.
- **Undocumented error surface.** Every raised or returned error, with its triggering condition; a caller
  cannot handle what is not listed.
- **Silent side effects.** State mutation, I/O, and resource claims that a caller cannot see from the
  signature.
- **`ensures:` weakened by the implementation.** If the body cannot guarantee the postcondition, the contract
  is wrong — fix one of them rather than leaving them disagreeing.
- **Documentation copied into a separate reference file.** It drifts. Generate or point instead.
- **Contract on the definition instead of the declaration**, in a language that separates the two, where
  callers read only the declaration.
