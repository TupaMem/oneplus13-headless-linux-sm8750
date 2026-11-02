/*
 * Host/device smoke tests and benchmarks for the experimental glibc runtime.
 * Passing on a host does not validate the OnePlus 13 kernel, device drivers,
 * boot chain, OTA flow, GPU, NPU, or thermal behavior.
 */

#define _GNU_SOURCE
#include <errno.h>
#include <float.h>
#include <inttypes.h>
#include <math.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <gnu/libc-version.h>
#include <sys/ipc.h>
#include <sys/sem.h>
#include <sys/shm.h>
#include <sys/syscall.h>
#include <sys/utsname.h>

#define THREAD_LIMIT 8
#define THREAD_ITERATIONS UINT64_C(5000000)
#define GEMM_SIZE 256
#define GEMM_REPEATS 8
#define SYSCALL_ITERATIONS 1000000

static int monotonic_ns(uint64_t *result) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return -1;
    }
    *result = (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
    return 0;
}

static int elapsed_ns(uint64_t start, uint64_t end, uint64_t *elapsed) {
    if (end <= start) {
        fprintf(stderr, "  -> Monotonic clock did not advance\n");
        return -1;
    }
    *elapsed = end - start;
    return 0;
}

static int test_environment(void) {
    struct utsname uts;
    long online_cpus;
    long page_size;

    printf("[TEST 1] Runtime and host introspection\n");
    if (uname(&uts) != 0) {
        perror("uname");
        return -1;
    }
    online_cpus = sysconf(_SC_NPROCESSORS_ONLN);
    page_size = sysconf(_SC_PAGESIZE);
    if (online_cpus <= 0 || page_size <= 0) {
        fprintf(stderr, "  -> Invalid sysconf result: CPUs=%ld page_size=%ld\n",
                online_cpus, page_size);
        return -1;
    }

    printf("  -> Kernel      : %s %s (%s)\n", uts.sysname, uts.release, uts.machine);
    printf("  -> Glibc       : %s (%s)\n", gnu_get_libc_version(), gnu_get_libc_release());
    printf("  -> Online CPUs : %ld (benchmark affinity is checked separately)\n", online_cpus);
    printf("  -> Page size   : %ld bytes\n", page_size);
    printf("  -> Status      : PASS\n\n");
    return 0;
}

static int test_sysv_ipc(void) {
    const size_t shm_size = 65536;
    const size_t words = shm_size / sizeof(uint64_t);
    int shmid = -1;
    int semid = -1;
    volatile uint64_t *shared = (void *)-1;
    bool attached = false;
    int result = -1;
    uint64_t start;
    uint64_t end;
    uint64_t duration;

    printf("[TEST 2] System V shared memory and semaphore lifecycle\n");
    if (monotonic_ns(&start) != 0) {
        perror("clock_gettime");
        return -1;
    }

    shmid = shmget(IPC_PRIVATE, shm_size, IPC_CREAT | IPC_EXCL | 0600);
    if (shmid < 0) {
        perror("shmget");
        goto cleanup;
    }
    shared = shmat(shmid, NULL, 0);
    if (shared == (void *)-1) {
        perror("shmat");
        goto cleanup;
    }
    attached = true;

    for (size_t i = 0; i < words; i++) {
        shared[i] = UINT64_C(0x534D38373530) ^ (uint64_t)i;
    }
    for (size_t i = 0; i < words; i++) {
        uint64_t expected = UINT64_C(0x534D38373530) ^ (uint64_t)i;
        if (shared[i] != expected) {
            fprintf(stderr, "  -> Shared-memory mismatch at word %zu\n", i);
            goto cleanup;
        }
    }
    if (shmdt((const void *)shared) != 0) {
        perror("shmdt");
        attached = false;
        goto cleanup;
    }
    attached = false;
    shared = (void *)-1;
    if (shmctl(shmid, IPC_RMID, NULL) != 0) {
        perror("shmctl(IPC_RMID)");
        goto cleanup;
    }
    shmid = -1;

    semid = semget(IPC_PRIVATE, 1, IPC_CREAT | IPC_EXCL | 0600);
    if (semid < 0) {
        perror("semget");
        goto cleanup;
    }
    union semun {
        int val;
        struct semid_ds *buf;
        unsigned short *array;
    } sem_arg;
    sem_arg.val = 1;
    if (semctl(semid, 0, SETVAL, sem_arg) < 0) {
        perror("semctl(SETVAL)");
        goto cleanup;
    }
    struct sembuf operation = { .sem_num = 0, .sem_op = -1, .sem_flg = 0 };
    if (semop(semid, &operation, 1) != 0) {
        perror("semop(P)");
        goto cleanup;
    }
    operation.sem_op = 1;
    if (semop(semid, &operation, 1) != 0) {
        perror("semop(V)");
        goto cleanup;
    }
    if (semctl(semid, 0, IPC_RMID) != 0) {
        perror("semctl(IPC_RMID)");
        goto cleanup;
    }
    semid = -1;

    if (monotonic_ns(&end) != 0) {
        perror("clock_gettime(end)");
        goto cleanup;
    }
    if (elapsed_ns(start, end, &duration) != 0) {
        goto cleanup;
    }
    printf("  -> Verified %zu-byte SHM and P/V semaphore cycle in %.2f us\n",
           shm_size, (double)duration / 1000.0);
    result = 0;

cleanup:
    if (attached && shmdt((const void *)shared) != 0) {
        perror("cleanup shmdt");
        result = -1;
    }
    if (shmid >= 0 && shmctl(shmid, IPC_RMID, NULL) != 0) {
        perror("cleanup shmctl(IPC_RMID)");
        result = -1;
    }
    if (semid >= 0 && semctl(semid, 0, IPC_RMID) != 0) {
        perror("cleanup semctl(IPC_RMID)");
        result = -1;
    }
    if (result == 0) {
        printf("  -> Status      : PASS\n\n");
    }
    return result;
}

static int test_syscall_latency(double *vdso_ns, double *syscall_ns) {
    struct timespec ts;
    uint64_t start;
    uint64_t end;
    uint64_t elapsed;

    printf("[TEST 3] vDSO clock_gettime and gettid syscall benchmark\n");
    if (monotonic_ns(&start) != 0) {
        perror("clock_gettime(start)");
        return -1;
    }
    for (int i = 0; i < SYSCALL_ITERATIONS; i++) {
        if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
            perror("clock_gettime(vDSO loop)");
            return -1;
        }
    }
    if (monotonic_ns(&end) != 0) {
        perror("clock_gettime(end)");
        return -1;
    }
    if (elapsed_ns(start, end, &elapsed) != 0) {
        return -1;
    }
    *vdso_ns = (double)elapsed / (double)SYSCALL_ITERATIONS;

    if (monotonic_ns(&start) != 0) {
        perror("clock_gettime(start)");
        return -1;
    }
    for (int i = 0; i < SYSCALL_ITERATIONS; i++) {
        if (syscall(SYS_gettid) < 0) {
            perror("syscall(SYS_gettid)");
            return -1;
        }
    }
    if (monotonic_ns(&end) != 0) {
        perror("clock_gettime(end)");
        return -1;
    }
    if (elapsed_ns(start, end, &elapsed) != 0) {
        return -1;
    }
    *syscall_ns = (double)elapsed / (double)SYSCALL_ITERATIONS;
    if (!isfinite(*vdso_ns) || !isfinite(*syscall_ns) || *vdso_ns <= 0.0 || *syscall_ns <= 0.0) {
        fprintf(stderr, "  -> Invalid timing result\n");
        return -1;
    }

    printf("  -> vDSO clock_gettime : %.2f ns/call (%d iterations)\n",
           *vdso_ns, SYSCALL_ITERATIONS);
    printf("  -> SYS_gettid         : %.2f ns/call (%d iterations)\n",
           *syscall_ns, SYSCALL_ITERATIONS);
    printf("  -> Status             : PASS\n\n");
    return 0;
}

struct worker_ctx {
    int cpu_target;
    int affinity_error;
    uint64_t checksum;
    atomic_uint_fast64_t *shared_counter;
};

static void *worker_fn(void *argument) {
    struct worker_ctx *ctx = argument;
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(ctx->cpu_target, &cpuset);
    ctx->affinity_error = pthread_setaffinity_np(pthread_self(), sizeof(cpuset), &cpuset);
    if (ctx->affinity_error != 0) {
        return NULL;
    }

    uint64_t accumulator = 0;
    for (uint64_t i = 0; i < THREAD_ITERATIONS; i++) {
        accumulator += i ^ UINT64_C(0xA5A5A5A5);
        if ((i & UINT64_C(63)) == 0) {
            atomic_fetch_add_explicit(ctx->shared_counter, 1, memory_order_relaxed);
        }
    }
    ctx->checksum = accumulator;
    return NULL;
}

static int test_multicore_scaling(double *iterations_per_second) {
    cpu_set_t allowed;
    int cpus[CPU_SETSIZE];
    int cpu_count = 0;
    int thread_count;
    pthread_t threads[THREAD_LIMIT];
    struct worker_ctx contexts[THREAD_LIMIT] = {0};
    int created = 0;
    atomic_uint_fast64_t counter;
    uint64_t start;
    uint64_t end;
    uint64_t elapsed;
    uint64_t expected_per_thread = (THREAD_ITERATIONS + 63) / 64;
    uint64_t expected_total;
    uint64_t actual_total;
    uint64_t checksum = 0;
    bool worker_failed = false;

    printf("[TEST 4] Pthread affinity and atomic-count correctness\n");
    CPU_ZERO(&allowed);
    if (sched_getaffinity(0, sizeof(allowed), &allowed) != 0) {
        perror("sched_getaffinity");
        return -1;
    }
    for (int cpu = 0; cpu < CPU_SETSIZE; cpu++) {
        if (CPU_ISSET(cpu, &allowed)) {
            cpus[cpu_count++] = cpu;
        }
    }
    if (cpu_count == 0) {
        fprintf(stderr, "  -> No CPUs are available to this process\n");
        return -1;
    }
    thread_count = cpu_count < THREAD_LIMIT ? cpu_count : THREAD_LIMIT;
    atomic_init(&counter, 0);

    if (monotonic_ns(&start) != 0) {
        perror("clock_gettime(start)");
        return -1;
    }
    for (int i = 0; i < thread_count; i++) {
        contexts[i].cpu_target = cpus[i];
        contexts[i].shared_counter = &counter;
        int error = pthread_create(&threads[i], NULL, worker_fn, &contexts[i]);
        if (error != 0) {
            fprintf(stderr, "  -> pthread_create: %s\n", strerror(error));
            goto join_created;
        }
        created++;
    }

join_created:
    for (int i = 0; i < created; i++) {
        int error = pthread_join(threads[i], NULL);
        if (error != 0) {
            fprintf(stderr, "  -> pthread_join: %s\n", strerror(error));
            worker_failed = true;
            continue;
        }
        if (contexts[i].affinity_error != 0) {
            fprintf(stderr, "  -> CPU %d affinity failed: %s\n", contexts[i].cpu_target,
                    strerror(contexts[i].affinity_error));
            worker_failed = true;
            continue;
        }
        checksum += contexts[i].checksum;
    }
    if (worker_failed || created != thread_count) {
        return -1;
    }
    if (monotonic_ns(&end) != 0) {
        perror("clock_gettime(end)");
        return -1;
    }
    if (elapsed_ns(start, end, &elapsed) != 0) {
        return -1;
    }

    expected_total = expected_per_thread * (uint64_t)thread_count;
    actual_total = atomic_load_explicit(&counter, memory_order_relaxed);
    if (actual_total != expected_total) {
        fprintf(stderr, "  -> Atomic count mismatch: expected=%" PRIu64 " actual=%" PRIu64 "\n",
                expected_total, actual_total);
        return -1;
    }
    *iterations_per_second =
        ((double)THREAD_ITERATIONS * (double)thread_count) / ((double)elapsed / 1e9);
    if (!isfinite(*iterations_per_second) || *iterations_per_second <= 0.0) {
        fprintf(stderr, "  -> Invalid throughput result\n");
        return -1;
    }

    printf("  -> Threads / allowed CPUs : %d / %d\n", thread_count, cpu_count);
    printf("  -> Atomic increments      : %" PRIu64 " (expected=%" PRIu64 ")\n",
           actual_total, expected_total);
    printf("  -> Work checksum          : 0x%" PRIx64 "\n", checksum);
    printf("  -> Loop iterations        : %.2f million/s (not hardware FLOPS)\n",
           *iterations_per_second / 1e6);
    printf("  -> Status                 : PASS\n\n");
    return 0;
}

static int test_gemm_compute(double *gflops) {
    const size_t elements = (size_t)GEMM_SIZE * GEMM_SIZE;
    const size_t bytes = elements * sizeof(double);
    double *a = aligned_alloc(64, bytes);
    double *b = aligned_alloc(64, bytes);
    double *c = aligned_alloc(64, bytes);
    uint64_t start;
    uint64_t end;
    uint64_t elapsed;
    double checksum = 0.0;
    int result = -1;

    printf("[TEST 5] FP64 matrix multiplication correctness and throughput\n");
    if (a == NULL || b == NULL || c == NULL) {
        perror("aligned_alloc");
        goto cleanup;
    }
    for (size_t i = 0; i < elements; i++) {
        a[i] = (double)(i % 100) * 0.01;
        b[i] = (double)((i + 7) % 100) * 0.01;
        c[i] = 0.0;
    }

    if (monotonic_ns(&start) != 0) {
        perror("clock_gettime(start)");
        goto cleanup;
    }
    for (int repeat = 0; repeat < GEMM_REPEATS; repeat++) {
        for (int i = 0; i < GEMM_SIZE; i++) {
            for (int k = 0; k < GEMM_SIZE; k++) {
                double aik = a[(size_t)i * GEMM_SIZE + (size_t)k];
                for (int j = 0; j < GEMM_SIZE; j++) {
                    c[(size_t)i * GEMM_SIZE + (size_t)j] +=
                        aik * b[(size_t)k * GEMM_SIZE + (size_t)j];
                }
            }
        }
    }
    if (monotonic_ns(&end) != 0) {
        perror("clock_gettime(end)");
        goto cleanup;
    }
    if (elapsed_ns(start, end, &elapsed) != 0) {
        goto cleanup;
    }

    for (int i = 0; i < GEMM_SIZE; i++) {
        for (int j = 0; j < GEMM_SIZE; j++) {
            double expected = 0.0;
            for (int repeat = 0; repeat < GEMM_REPEATS; repeat++) {
                for (int k = 0; k < GEMM_SIZE; k++) {
                    expected += a[(size_t)i * GEMM_SIZE + (size_t)k] *
                                b[(size_t)k * GEMM_SIZE + (size_t)j];
                }
            }
            double actual = c[(size_t)i * GEMM_SIZE + (size_t)j];
            double tolerance = 128.0 * DBL_EPSILON * fmax(1.0, fabs(expected));
            if (!isfinite(actual) || fabs(actual - expected) > tolerance) {
                fprintf(stderr, "  -> GEMM mismatch at (%d,%d): expected %.17g, got %.17g\n",
                        i, j, expected, actual);
                goto cleanup;
            }
            checksum += actual;
        }
    }

    *gflops = (2.0 * GEMM_SIZE * GEMM_SIZE * GEMM_SIZE * GEMM_REPEATS) /
              (double)elapsed;
    if (!isfinite(*gflops) || *gflops <= 0.0 || !isfinite(checksum)) {
        fprintf(stderr, "  -> Invalid GEMM result\n");
        goto cleanup;
    }
    printf("  -> Matrix / repeats : %dx%d / %d\n", GEMM_SIZE, GEMM_SIZE, GEMM_REPEATS);
    printf("  -> Checksum         : %.6f (all elements checked)\n", checksum);
    printf("  -> Throughput       : %.2f GFLOP/s (host-dependent benchmark)\n", *gflops);
    printf("  -> Status           : PASS\n\n");
    result = 0;

cleanup:
    free(a);
    free(b);
    free(c);
    return result;
}

int main(void) {
    double vdso_ns = 0.0;
    double syscall_ns = 0.0;
    double iterations_per_second = 0.0;
    double gflops = 0.0;

    printf("OnePlus 13 (SM8750) experimental runtime tests\n");
    printf("Host-only PASS does not certify device compatibility or safe flashing.\n\n");
    if (test_environment() != 0 || test_sysv_ipc() != 0 ||
        test_syscall_latency(&vdso_ns, &syscall_ns) != 0 ||
        test_multicore_scaling(&iterations_per_second) != 0 ||
        test_gemm_compute(&gflops) != 0) {
        fprintf(stderr, "[FAIL] One or more runtime tests failed.\n");
        return EXIT_FAILURE;
    }

    printf("[PASS] All 5 checks completed. Measurements are specific to this host.\n");
    printf("       vDSO=%.2f ns | syscall=%.2f ns | loop=%.2f Miter/s | GEMM=%.2f GFLOP/s\n",
           vdso_ns, syscall_ns, iterations_per_second / 1e6, gflops);
    return EXIT_SUCCESS;
}
