"""Credential-free, bounded semaphore and spawned-child check in the Runner."""
import multiprocessing as mp


def child(lock, sender):
    acquired = lock.acquire(timeout=2)
    try:
        sender.send(acquired)
    finally:
        if acquired:
            lock.release()
        sender.close()


def main():
    # fork uses unnamed semaphores; spawn exercises the named /dev/shm path.
    for method in ('fork', 'spawn'):
        ctx = mp.get_context(method)
        lock = ctx.Lock()
        receiver, sender = ctx.Pipe(duplex=False)
        process = ctx.Process(target=child, args=(lock, sender))
        started = False
        try:
            process.start()
            started = True
            sender.close()
            if not receiver.poll(5) or receiver.recv() is not True:
                return 1
            process.join(5)
            if process.exitcode != 0:
                return 1
        finally:
            receiver.close()
            sender.close()
            if started:
                if process.is_alive():
                    process.kill()
                process.join(2)
                process.close()
    print('PASS_IPC')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('FAIL_IPC')
        raise SystemExit(1)
