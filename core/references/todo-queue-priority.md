# TODO Queue Priority

Process tasks from the queue HEAD first (not tail). This rule prevents zombie tasks from accumulating.

## Rule

On wake/start, read TODO.md from TOP:

1. Check the queue HEAD (first non-done entry), not the latest tail entry.
2. If the head entry task_id is already `[superseded]` or marked KB ✅ MERGED, skip it.
3. If the head entry age > 3 days with no matching DELIVERY.md update, mark `[superseded]` and skip.
4. Otherwise process the head entry.
5. When the head is done, move to the next `[pending]` entry.

## Why

`dispatch_task.py` appends to the tail of TODO.md. If a seat reads tail-first, the head tasks become zombie entries that are never processed — they sit permanently unread while newer tasks at the tail get attention.

**Short form**: 先看队首 / queue head, not tail. Skip `[superseded]` or KB ✅ MERGED; age-out tasks >3 days with no DELIVERY.md match; process head then next `[pending]`.
