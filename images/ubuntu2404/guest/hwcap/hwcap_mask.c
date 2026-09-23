// hwcap_mask.so — LD_PRELOAD shim that masks ARMv9 HWCAP/HWCAP2 feature bits
// from getauxval(). Apple Virtualization.framework on M4/M5 hosts advertises
// SVE/SVE2/SME/SME2 (and related v9 features) to the guest, but the
// instructions trap through the virtualization stack, causing intermittent
// SIGILL crashes in JIT-compiled and SIMD-optimized code paths (Chromium V8,
// Skia, BoringSSL, libjpeg-turbo, zlib). Masking the bits forces every
// library onto its baseline NEON paths, which work correctly.
//
// Approach proven by the astonish project (schardosin/astonish commit
// e90577c) against the same defect class (podman issue #28312).
#define _GNU_SOURCE
#include <dlfcn.h>
#include <sys/auxv.h>
#include <asm/hwcap.h>

#ifndef AT_HWCAP
#define AT_HWCAP 16
#endif
#ifndef AT_HWCAP2
#define AT_HWCAP2 26
#endif
// Bit definitions newer than some userspace headers (kernel uapi layout).
#ifndef HWCAP2_SME_B16F32
#define HWCAP2_SME_B16F32 (1UL << 28)
#endif
#ifndef HWCAP2_SME_F32F32
#define HWCAP2_SME_F32F32 (1UL << 29)
#endif
#ifndef HWCAP2_SME_FA64
#define HWCAP2_SME_FA64 (1UL << 30)
#endif
#ifndef HWCAP2_EBF16
#define HWCAP2_EBF16 (1UL << 32)
#endif
#ifndef HWCAP2_SVE_EBF16
#define HWCAP2_SVE_EBF16 (1UL << 33)
#endif
#ifndef HWCAP2_SVE2P1
#define HWCAP2_SVE2P1 (1UL << 36)
#endif
#ifndef HWCAP2_SME2
#define HWCAP2_SME2 (1UL << 37)
#endif
#ifndef HWCAP2_SME2P1
#define HWCAP2_SME2P1 (1UL << 38)
#endif
#ifndef HWCAP2_SME_I16I32
#define HWCAP2_SME_I16I32 (1UL << 39)
#endif
#ifndef HWCAP2_SME_BI32I32
#define HWCAP2_SME_BI32I32 (1UL << 40)
#endif

// HWCAP bits to clear (ARMv9 family): SVE only; the rest of v9 lives in HWCAP2.
static const unsigned long HWCAP_DROP = HWCAP_SVE;
// HWCAP2 bits to clear: the whole SVE2/SME/SME2 family plus BF16, I8MM, BTI.
static const unsigned long HWCAP2_DROP =
    HWCAP2_SVE2 | HWCAP2_SVEAES | HWCAP2_SVEPMULL | HWCAP2_SVEBITPERM |
    HWCAP2_SVESHA3 | HWCAP2_SVESM4 | HWCAP2_SVEI8MM | HWCAP2_SVEF32MM |
    HWCAP2_SVEF64MM | HWCAP2_SVEBF16 | HWCAP2_I8MM | HWCAP2_BF16 |
    HWCAP2_BTI | HWCAP2_SME | HWCAP2_SME_I16I64 | HWCAP2_SME_F64F64 |
    HWCAP2_SME_I8I32 | HWCAP2_SME_F16F32 | HWCAP2_SME_B16F32 |
    HWCAP2_SME_F32F32 | HWCAP2_SME_FA64 | HWCAP2_EBF16 | HWCAP2_SVE_EBF16 |
    HWCAP2_SVE2P1 | HWCAP2_SME2 | HWCAP2_SME2P1 | HWCAP2_SME_I16I32 |
    HWCAP2_SME_BI32I32;

unsigned long getauxval(unsigned long type) {
    static unsigned long (*real_getauxval)(unsigned long) = 0;
    if (!real_getauxval) real_getauxval = dlsym(RTLD_NEXT, "getauxval");
    unsigned long value = real_getauxval(type);
    if (type == AT_HWCAP) return value & ~HWCAP_DROP;
    if (type == AT_HWCAP2) return value & ~HWCAP2_DROP;
    return value;
}
