---
myst:
  html_meta:
    description: "Reference for the errors and warnings fmsave raises."
---

# Errors

Every error fmsave raises on purpose is a `FmsaveError`; every warning it issues on purpose is a
`FmsaveWarning`. `GateCheckError` is the one exception that is also more specific than its base:
it is the `ReaderCheckError` a save opened with `strict=True` raises for a failed check.

fmsave sets no fixed size limit on a save. A part that claims or decompresses to far more than
its compressed bytes could plausibly hold raises `CorruptSaveError` before that memory is spent;
the message gives the ratio, what real saves show, and asks for a report if the game opens the
save.

```{eval-rst}
.. autoexception:: fmsave.FmsaveError
   :show-inheritance:
.. autoexception:: fmsave.NotAFmSaveError
   :show-inheritance:
.. autoexception:: fmsave.CorruptSaveError
   :show-inheritance:
.. autoexception:: fmsave.UnsupportedGameError
   :show-inheritance:
.. autoexception:: fmsave.ReaderCheckError
   :show-inheritance:
.. autoexception:: fmsave.GateCheckError
   :show-inheritance:
.. autoexception:: fmsave.SaveChangedError
   :show-inheritance:
.. autoexception:: fmsave.SaveClosedError
   :show-inheritance:
.. autoexception:: fmsave.AmbiguousNameError
   :show-inheritance:
.. autoexception:: fmsave.FmsaveWarning
   :show-inheritance:
.. autoexception:: fmsave.UnknownBuildWarning
   :show-inheritance:
.. autoexception:: fmsave.ReaderCheckWarning
   :show-inheritance:
```
