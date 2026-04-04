# Устранение неисправностей процессов

## Definitions

**Troubleshooting процессов** — систематическая диагностика проблем с процессами в Linux: анализ кодов завершения, утечек памяти, аварийных завершений (coredump), зомби-процессов и миграция состояний (CRIU).

**Код завершения (Exit code)** — целочисленное значение (0–255), возвращаемое процессом при завершении. Подробное описание — в [Коды возврата в Shell](../../../Shell/exit_codes.md).

**Дамп памяти (Coredump)** — снимок адресного пространства процесса в момент аварийного завершения (сигналы `SIGSEGV`, `SIGFPE`, `SIGQUIT`); используется для посмертной отладки — см. [signals](../signals.md).

**CRIU (Checkpoint/Restore In Userspace)** — утилита для заморозки процесса с сохранением состояния (память, PID, файлы, сокеты) и последующего восстановления — см. [checkpoint_restore](./checkpoint_restore.md).

---

## Basic Concepts

### Три столпа observability применительно к процессам

1. **Метрики** — CPU, память, I/O (`top`, `ps`, `pidstat`)
2. **Логи** — вывод приложения, `syslog`, `journalctl`
3. **Трассировки** — `strace`, `perf`, `bpftrace`

Подробнее: [Observability Overview](../../../../Concepts/Observability_and_Monitoring/observability_definitions.md)

### Основные инструменты диагностики

- **Коды завершения** — анализ `$?` после выполнения команды — [exit_codes](../../../Shell/exit_codes.md)
- **Состояния процессов** — колонка STAT в выводе `ps` (`R`, `S`, `Z`, `D`, `T`) — [ps](../../../Diagnostics/Processes/ps.md)
- **Открытые файлы** — утилита [`lsof`](../../../Diagnostics/Processes/lsof.md)
- **Трассировка системных вызовов** — [`strace`](../../../Diagnostics/Troubleshooting/tracing_and_debugging.md)
- **Namespaces** — [`nsenter`](../../namespaces.md) для входа в контекст процесса

---

## Practical Scenarios

| Сценарий | Файл | Краткое описание |
|----------|------|-----------------|
| CRIU checkpoint/restore | [checkpoint_restore](./checkpoint_restore.md) | Заморозка и восстановление процесса, миграция между терминалами |
| Утечки памяти | [debugging](./debugging.md#диагностика-утечек-памяти) | Valgrind, `/proc/<PID>/status`, strace |
| Анализ coredump | [debugging](./debugging.md#анализ-сбоев-coredump) | `ulimit -c`, `coredumpctl`, gdb |
| Зомби-процессы | [debugging](./debugging.md#зомби-процессы) | Диагностика через `ps`, устранение через `SIGCHLD` |

---

## Additional Information

- Связь с наблюдаемостью системы — [Observability Overview](../../../../Concepts/Observability_and_Monitoring/observability_definitions.md)
- Сигналы и их обработка — [signals](../signals.md)
- Мониторинг процессов — [practical_scenarios](../practical_scenarios.md)
- Пространства имён — [namespaces](../../namespaces.md)
