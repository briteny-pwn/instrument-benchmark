# Resolution summary

Polling thread fires OnXYStagePositionChanged callbacks during moves. The thread now wakes immediately when a move starts via a condition variable.
