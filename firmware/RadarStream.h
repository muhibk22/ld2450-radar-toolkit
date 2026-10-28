#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// No Arduino dependencies: exercise exactly this framing/queue policy on host.
namespace RadarStream {
static const size_t FRAME_BYTES = 30;
struct Framer {
  uint8_t bytes[FRAME_BYTES];
  size_t used = 0;
  bool push(uint8_t value, uint8_t* frame) {
    bytes[used++] = value;
    if (used < FRAME_BYTES) return false;
    if (bytes[0] == 0xAA && bytes[1] == 0xFF && bytes[2] == 3 && bytes[3] == 0 &&
        bytes[28] == 0x55 && bytes[29] == 0xCC) {
      memcpy(frame, bytes, FRAME_BYTES);
      used = 0;
      return true;
    }
    memmove(bytes, bytes + 1, FRAME_BYTES - 1);
    used = FRAME_BYTES - 1;
    return false;
  }
};

struct Output {
  uint8_t active[128], latest[FRAME_BYTES];
  size_t length = 0, offset = 0;
  bool hasLatest = false;
  uint32_t startedAt = 0, latestAt = 0;
  void reset() { length = offset = 0; hasLatest = false; }
  void queueFrame(const uint8_t* frame, uint32_t now) {
    memcpy(latest, frame, FRAME_BYTES);
    hasLatest = true;
    latestAt = now;
  }
  bool queueNotice(const uint8_t* data, size_t size, uint32_t now) {
    if (length || hasLatest || size > sizeof(active)) return false;
    memcpy(active, data, size);
    length = size; offset = 0; startedAt = now;
    return true;
  }
  const uint8_t* front(uint32_t now, size_t& size) {
    if (!length && hasLatest) {
      hasLatest = false;
      if (uint32_t(now - latestAt) <= 500) {
        memcpy(active, latest, FRAME_BYTES);
        length = FRAME_BYTES; offset = 0; startedAt = now;
      }
    }
    size = length - offset;
    return size ? active + offset : nullptr;
  }
  void advance(size_t count) {
    if (count > length - offset) count = length - offset;
    offset += count;
    if (offset == length) length = offset = 0;
  }
  bool expired(uint32_t now) const {
    return length && uint32_t(now - startedAt) >= 250;
  }
};
}
