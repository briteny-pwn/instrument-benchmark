# Resolution summary

Setting an ROI previously led to a crash (uncaught exception).  Turns out that the camera first has to stop grabbing before one can set the images sizes.  Also fixed a problem with stale width and height that sometimes would cause insertion in the sequence buffer to fail (I am not sure how this CMMError from the circular buffer InsertImage function is handled).

Also cleaned up the code a bit.  Still quite messy.
