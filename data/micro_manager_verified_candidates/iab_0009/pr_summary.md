# Resolution summary

**Summary**

- Fix hard crashes caused by unsynchronized concurrent modification of MM property allowed-values containers (`std::map`) from Vimba SDK invalidation callback threads
- Add `std::recursive_mutex` to serialize `onProperty()` calls, preventing concurrent `ClearAllowedValues()` / `SetAllowedValues()` from corrupting the map's internal tree
- Add `std::atomic<bool>` init guard to skip Vimba callbacks that arrive before `setupProperties()` completes, preventing a race between property creation and callback-driven updates
- Use `try_to_lock` in the Vimba callback to avoid blocking the SDK's callback thread, which would deadlock with in-progress Vimba feature queries
- Refresh property limits before programmatic `SetProperty` calls

**Context**

The Vimba SDK fires feature invalidation callbacks on separate worker threads (documented in `VmbCTypeDefinitions.h`). These callbacks call `UpdateProperty() → onProperty() → setAllowedValues() → SetAllowedValues() → ClearAllowedValues()`. When multiple callbacks fire simultaneously, the `std::map::clear()` on one thread races with iteration/insertion on another, causing heap corruption detected as a debug CRT breakpoint (op
