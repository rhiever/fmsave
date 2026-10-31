---
myst:
  html_meta:
    description: "Reference for the errors and warnings fmsave raises."
---

# Errors

Every error fmsave raises on purpose is a `FmsaveError`; every warning it issues on purpose is a
`FmsaveWarning`. Two errors are more specific than their base. `GateCheckError` is the
`ReaderCheckError` a save opened with `strict=True` raises for a failed check.
`SaveTooLargeError` is the `CorruptSaveError` for a save that holds more data than fmsave's
memory limits allow; the save itself may be sound.

```{eval-rst}
.. autoexception:: fmsave.FmsaveError
   :show-inheritance:
.. autoexception:: fmsave.NotAFmSaveError
   :show-inheritance:
.. autoexception:: fmsave.CorruptSaveError
   :show-inheritance:
.. autoexception:: fmsave.SaveTooLargeError
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
