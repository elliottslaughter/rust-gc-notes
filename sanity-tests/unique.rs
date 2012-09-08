fn debug_ptr(ptr: uint, root: uint) {
    io::println(#fmt("unique root 0x%08x box 0x%08x", root, ptr));
}

fn main() {
    let x = ~3;
    let y = ~4;
    let z = ~5;
    let w = ~6;
    unsafe {
        debug_ptr(unsafe::reinterpret_cast(&x), unsafe::reinterpret_cast(&ptr::addr_of(x)));
        debug_ptr(unsafe::reinterpret_cast(&y), unsafe::reinterpret_cast(&ptr::addr_of(y)));
        debug_ptr(unsafe::reinterpret_cast(&z), unsafe::reinterpret_cast(&ptr::addr_of(z)));
        debug_ptr(unsafe::reinterpret_cast(&w), unsafe::reinterpret_cast(&ptr::addr_of(w)));
    }
    fail;
}
