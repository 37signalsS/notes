# Анализ ошибок и сбоев (Error and Crash Analysis)

## Определения

**Анализ сбоев (Crash Analysis)** — процесс систематической диагностики причин аварийного завершения программного обеспечения или операционной системы. В отличие от стандартного мониторинга, фокус здесь смещен на **Root Cause Analysis (RCA)** критических инцидентов, приводящих к остановке процессов (`SIGSEGV`, `SIGABRT`) или краху всей системы (**Kernel Panic**).

**Классификация критических сбоев:**

| Тип инцидента | Проявление | Механизм фиксации | Основной документ |
| :--- | :--- | :--- | :--- |
| **Application Crash** | Остановка процесса (Segmentation Fault) | Coredump (дамп памяти) | [Отладка через Coredump](../../Core/processes/Troubleshooting/debugging.md) |
| **OOM (Out Of Memory)** | Процесс «исчезает» (убит ядром) | Системный лог (dmesg) | [Механизм OOM Killer](../../Core/processes/oom_killer_mechanism.md) |
| **Kernel Panic** | Система зависает или перезагружается | kdump (vmcore), pstore | [Паника ядра](../../Core/kernel/kernel_panic.md) |
| **Container Crash** | Состояние `CrashLoopBackOff` в K8s | `kubectl logs --previous` | [Диагностика CrashLoopBackOff](../../../Kubernetes/Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md) |
| **Watchdog Reset** | Мгновенная перезагрузка без логов | IPMI SEL, Hardware Logs | [Диагностика перезагрузки](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) |

## Базовые концепции

### Сбои в пространстве пользователя (User Space)

Возникают при нарушении логики работы с памятью или явном вызове `abort()`. Современным стандартом сбора данных является **`systemd-coredump`**.

1.  **Автоматизация:** При крахе ядро передает управление обработчику `systemd-coredump`, который сжимает дамп и сохраняет его в `/var/lib/systemd/coredump/`.
2.  **Метаданные:** В журнал `journald` записываются расширенные данные: регистры процессора, список загруженных библиотек и базовая трассировка стека.
3.  **Доступ:** Инструмент `coredumpctl` позволяет мгновенно найти нужный сбой без ручного поиска файлов.

### Сбои в пространстве ядра (Kernel Space)

Любой критический баг в драйвере или модуле ядра приводит к немедленной остановке системы (**Kernel Panic**).

*   **Механизм kdump:** Резервирует часть RAM для «аварийного» ядра, которое сохраняет состояние упавшей системы в файл `vmcore` на диск.
*   **Механизм pstore (Ramoops):** Позволяет сохранять последние сообщения `dmesg` в специальной области памяти, которая не очищается при мягкой перезагрузке. Это критично, если диск был недоступен в момент сбоя.

### Ошибки нехватки памяти (OOM)

Важно различать два типа OOM:
*   **System OOM:** Исчерпана вся физическая память сервера.
*   **Memcg OOM (Cgroup/Container):** Процесс превысил лимит контейнера (например, в Kubernetes). В логах dmesg ищите строку `oom-kill:constraint=CONSTRAINT_MEMCG`.

## Практические сценарии

### Алгоритм первичной диагностики (RCA)

Если сервер внезапно перезагрузился или «пропал» критический процесс:

1.  **Проверка триггера OOM:**
    ```bash
    journalctl -k -g "Out of memory"
    ```
2.  **Поиск дампов пользовательских процессов:**
    ```bash
    coredumpctl list
    ```
3.  **Проверка факта Kernel Panic (kdump):**
    ```bash
    ls -R /var/crash/
    ```
4.  **Чтение «посмертных» логов (pstore):**
    ```bash
    mount -t pstore pstore /sys/fs/pstore
    cat /sys/fs/pstore/dmesg-ramoops-0
    ```
5.  **Анализ логов предыдущей сессии:**
    ```bash
    journalctl -p err -b -1
    ```

### Анализ краха приложения в контейнере (Kubernetes)

```bash
# 1. Посмотреть логи предыдущей инстанции упавшего пода
kubectl logs <pod_name> --previous

# 2. Проверить причину завершения (Reason: OOMKilled vs Error)
kubectl describe pod <pod_name>
```

### Глубокая отладка (Post-Mortem)

#### Работа с coredump
```bash
# Посмотреть информацию о сбое и backtrace без запуска отладчика
coredumpctl info <PID>

# Запустить отладку последнего сбоя конкретного бинарника
coredumpctl debug /usr/bin/nginx
```

#### Работа с дампом ядра
```bash
# Требует установленного пакета crash и kernel-debuginfo
sudo crash /usr/lib/debug/boot/vmlinux-$(uname -r) /var/crash/<date>/vmcore
```

## Современные инструменты и мониторинг

### Проактивное обнаружение (eBPF)
Использование eBPF позволяет отслеживать признаки сбоя до того, как система остановится:
*   **Falco / Tetragon:** Логируют аномальные системные вызовы.
*   **bpftrace:** Позволяет «на лету» подцепиться к функциям ядра (например, `kprobe:panic`) для сбора контекста.

### Автоматизированные отчеты
*   **ABRT (Automatic Bug Reporting Tool):** Стандарт для RHEL-семейства.
*   **Apport:** Аналог для Ubuntu/Debian.

## Дополнительная информация

### Матрица инструментов

| Задача | Инструмент | Уровень |
| :--- | :--- | :--- |
| Поиск coredump | `coredumpctl` | User Space (systemd) |
| Отладка стека | `gdb` | User Space |
| Анализ vmcore | `crash` | Kernel Space |
| Восстановление логов | `pstore / ramoops` | Kernel Space |
| Анализ OOM | `dmesg`, `journalctl` | Ядро / Контейнеры |

### См. также
- [**Отладка процессов: Coredump**](../../Core/processes/Troubleshooting/debugging.md)
- [**Паника ядра: механизмы и анализ**](../../Core/kernel/kernel_panic.md)
- [**Диагностика OOM Killer**](../../Core/processes/oom_killer_diagnostics.md)
- [**Обзор системы логирования**](./logging_overview.md)
- [**Диагностика причин перезагрузки**](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md)
- [**Диагностика CrashLoopBackOff**](../../../Kubernetes/Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md)
