# Rust Precise GC Implementation Notes

## Overview

These are my notes from implementing precise GC for Rust at Mozilla
Research during my internship over the summer of 2012. An overview of
my work follows in the rest of this file.

Quick Links:

  * [Talk for Mozilla Research (2012-08-30)](https://github.com/elliottslaughter/rust-gc-talk)
  * [Detailed Log](https://raw.github.com/elliottslaughter/rust-gc-notes/master/notes.org)

## Background

At the beginning of the summer, Rust used reference counting plus a
cycle collector to manage the task-local heap. The cycle collector was
slow and buggy, so in practice it was never actually used.

The Rust team had considered upgrading to a proper GC for some
time. Patrick (pcwalton) had even done some initial work to check the
feasibility of GC. Patrick found that LLVM's existing GC support
forced all GC'd pointers to be pinned on the stack. Thus, if we wanted
a fast, precise GC, we would have to hack LLVM's GC infrastructure to
support optimization of GC pointers.

## Approaches Considered

### Conservative

While not precise, it is worth noting conservative GC because it is
relatively simple and easy to implement, and it requires absolutely no
modifications to LLVM, and only minimal support from the Rust
compiler. Patrick has worked on a conservative GC for Rust, and it
looks promising so far, but whether or not it can perform well is
still an unknown.

### Explicit LLVM register roots

But if we really wanted to implement a precise GC in Rust, then one
way or another we'd need LLVM's cooperation in telling us where GC
roots live on the stack. The most obvious way to do that would be to
add an LLVM intrinsic to parallel LLVM's existing [`gcroot`
intrinsic](http://llvm.org/docs/GarbageCollection.html#gcroot), but
for registers (a `gcregroot`, in effect).

Unfortunately, LLVM's optimization infrastructure wasn't built with
maintaining GC invariants in mind. In addition to teaching LLVM's
`mem2reg` and `reg2mem` passes how to move pointers between `gcroot`
and `gcregroot`, we would have to go through all the LLVM optimization
passes to make sure none of the GC invariants are violated. Perhaps
even worse, different GC algorithms might need to maintain different
invariants, and so this would be potentially language-specific. The
LLVM team wasn't enthusiastic about this approach, and it would be
much more than a summer's work anyway, so we looked for other
approaches.

### Automatic roots

So rather than explicitly marking roots at the LLVM IR level, we
decided to automatically infer roots in an LLVM pass. By positioning
this pass after other LLVM IR optimizations, we could free LLVM from
having to maintain GC invariants in its optimizations.

The disadvantage was that this would limit what GC algorithms we could
make use of. Specifically, LLVM would be free to make copies of
pointers and put them anywhere, so we wouldn't necessarily know about
all copies of given pointer. So we wouldn't be able to implement any
moving GC algorithms with this approach, leaving primarily
mark-and-sweep GC algorithms on the table.

Perhaps more troubling was the additional hacking that would be
required to lower LLVM's IR into machine code. Since we ran the
automatic root pass after optimizations, some GC pointers would be in
virtual registers in the IR. And LLVM had no way to represent GC
register roots at the machine level.

We decided to try adding a fake LLVM machine instruction to represent
a GC register roots. The automatic root pass would add these fake
instructions into the IR, and then the machine translation layers
would pass these on down to the GC assembly printer which would spit
out the stack map into the resulting module. This would require, among
other things, changes to the LLVM DAG-based instruction selector, and
to each machine-specific backend. It sounded painful, but we hoped it
would be feasible.

## Beyond GC: Cleanup

A GC, beyond just collecting garbage, also happens to useful for other
purposes. We realized that a stack walker with detailed information
about what lives on the stack could also potentially serve as a
replacement for the C++ exception handler. Since in Rust failure
happens at the level of entire tasks, we would need to worry about
restoring the stack to a particular state; we could just cleanup
anything living on the stack and wipe out the entire task-local heap
in one go.

The difficulty would be running destructors on non-pointer types
stored on the stack. Take, for example, a file descriptor, stored in a
stack-allocated struct with a destructor. Missing the struct would
mean leaking the file descriptor. But no pointer to the struct
actually lives on the stack. So to combat this we would need our
compiler to explicitly emit pointers to these stack-allocated structs,
so that the automatic root pass could find those structs on the stack.

## Better Static Type Information

Unfortunately, even with explicit pointer roots to stack allocations,
LLVM's type information is too low-level to know what destructors to
run for each type. E.g. a file descriptor and a refcount would both be
represented as an int in LLVM's type system. For heap-allocated
objects, this wouldn't matter, because in Rust each heap allocation
has a header describing the type that lives within. But for stack
allocations, we had no such header.

Since we opted for automatic root insertion at the IR level, we
wouldn't have explicit `gcroot` intrinsics to tell us what Rust type
each alloca corresponded too. So we added static type information to
LLVM's type system by giving meaning to the address space component of
LLVM's pointer type.

LLVM pointers live in an address space (represented by an unsigned
integer), which has meaning to various LLVM backends. By default, LLVM
only gives meaning to address spaces 0 and 1. Address space 0
corresponds to normal, unmanaged pointers. Address space 1 corresponds
to generic GC'd boxes.

We decided to make use of the other LLVM address spaces. Address space
2 and up would refer to stack-allocated types in need of cleanup. The
Rust compiler would choose address spaces for its types, and then emit
a map from address space to static type information. The LLVM
automatic root pass would then look up the address space of the
pointer, and insert the static type information into `gcroot`
intrinsic it created to track the root. In this way, we would be able
to get detailed type information all the way to the Rust runtime.

## Status as of 2012-09-07

GC-based cleanup works, with optimizations off, on a large percentage
of test cases in the Rust test suite, in addition to the Rust compiler
itself. The vast majority of run-pass tests pass, and most of the
run-fail tests pass.

The remaining failing tests mostly correspond to specific types which,
for whatever reason, don't get rooted properly by the GC. For example,
forms of the `fail` expression taking a string parameter will allocate
a string, but then not store it into an alloca. Thus the GC in its
current form is unable to find the string on the stack, leaking
memory.

Optimizations don't work because I didn't have time to get around to
fixing LLVM's SelectionDAG to work with our fake `gcregroot` machine
instructions. I'm guessing it's a month project for someone who
actually knows LLVM's machine layer, or a multi-month project for
someone who only knows LLVM's IR layer.

In the meantime, Patrick's conservative GC has made progress. Maybe
the way forward will be conservative GC, at least in the near term. I
doubt that we'd want to stick with conservative GC forever, but that
depends a lot on how much more resistance LLVM gives us.

## Testing GC-based Cleanup

To test GC-based cleanup on an individual Rust file, invoke Rust with
optimizations off and with `--gc -Z no-landing-pads`.

    rustc --gc -Z no-landing-pads example.rs

Running the test suite is currently a little more complicated, because
the test runner has a bug preventing itself from being compiled with
GC on.

Apply the following patch to turn on GC in individual test cases.

    diff --git a/mk/tests.mk b/mk/tests.mk
    index 851c5b8..8205ce9 100644
    --- a/mk/tests.mk
    +++ b/mk/tests.mk
    @@ -360,7 +360,7 @@ CTEST_COMMON_ARGS$(1)-T-$(2)-H-$(3) :=						\
             --rustc-path $$(HBIN$(1)_H_$(3))/rustc$$(X)			\
             --aux-base $$(S)src/test/auxiliary/                 \
             --stage-id stage$(1)-$(2)							\
    -        --rustcflags "$$(CFG_RUSTC_FLAGS) --target=$(2)"	\
    +        --rustcflags "$$(CFG_RUSTC_FLAGS) --gc -Z no-landing-pads --target=$(2)"	\
             $$(CTEST_TESTARGS)
     
     CFAIL_ARGS$(1)-T-$(2)-H-$(3) :=					\

Then build Rust as follows.

    ./configure --disable-optimize
    RUSTFLAGS='-O' make
    make check -k

This will build libcore with GC off, but with GC on in each
testcases. Necessarily this will cause some leakage, because libcore
itself allocates memory.

To build with GC on in both libcore and each test, use the following
invokation instead.

    ./configure --disable-optimize
    RUSTFLAGS='--gc -Z no-landing-pads' make
    make check -k

This might crash more, because libcore still has a few issues with GC
which tend to pop up more frequently just because of how pervasively
libcore is used.

## Other Files in This Repository

  * `notes.org` -- I kept a daily log which is a detailed record of
    everything I tried during the summer. I don't expect it to be
    especially helpful to anyone, but it might shed light on e.g. what
    exact configurations I was testing, etc.

  * `rebuild.sh` -- The script I used to run tests with GC enabled in
    various configurations.

  * `sanity-tests/` -- A couple simple tests that should always pass.

  * `summarize.py` -- A script I used to summarize results from test
    runs, and diagnosing failures.

  * `summary-2012-09-06.log` -- The output from my last test run, on a
    32-bit Ubuntu machine.

  * `test-gc.diff` -- The same diff as above, in case you like using
    the patch command. Turns on GC within testcases, without enabling
    GC for either the test runner, or libcore.

## Other Resources

I also gave a talk summarizing my work over the summer. If you've read
this far, you probably won't need it, but you might find it
interesting.

https://github.com/elliottslaughter/rust-gc-talk
