#include "../firmware/RadarStream.h"
#include <assert.h>
#include <iostream>
int main() {
  uint8_t frame[30] = {0xAA,0xFF,3,0}, result[30];
  frame[28]=0x55; frame[29]=0xCC;
  RadarStream::Framer framer;
  for(int i=0;i<17;++i) assert(!framer.push(0x12,result));
  for(int i=0;i<29;++i) assert(!framer.push(frame[i],result));
  assert(framer.push(frame[29],result));
  assert(!memcmp(frame,result,30));
  RadarStream::Output slow,fast;
  slow.queueFrame(frame,0);
  size_t n=0;
  const uint8_t* p=slow.front(0,n); assert(n==30 && p[0]==0xAA);
  slow.advance(7);
  frame[4]=42; slow.queueFrame(frame,100); fast.queueFrame(frame,100);
  p=slow.front(100,n); assert(n==23 && p[0]==0); // partial frame not overwritten
  p=fast.front(100,n); assert(n==30 && p[4]==42); fast.advance(n);
  assert(slow.expired(250)); assert(!fast.expired(250)); // independent clients
  slow.advance(23); p=slow.front(251,n); assert(n==30 && p[4]==42);
  slow.reset(); slow.queueFrame(frame,10); assert(!slow.front(600,n)); // no stale replay
  const uint8_t msg[]={1,2}; assert(slow.queueNotice(msg,2,700));
  slow.queueFrame(frame,701); slow.front(701,n); assert(n==2); slow.advance(2);
  slow.front(702,n); assert(n==30); // control bytes cannot interleave partial frames
  std::cout << "firmware framing, partial writes, isolation, expiry: PASS\n";
}
