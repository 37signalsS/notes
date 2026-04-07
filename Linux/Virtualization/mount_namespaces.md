# Mount Namespaces и Mount Propagation

## Definitions

**Mount namespace (`CLONE_NEWNS`)** — тип namespace в Linux, изолирующий таблицу монтирования для группы процессов. Каждый mount namespace получает собственную копию точек монтирования родителя при создании.

**Mount propagation** — механизм определения того, как события монтирования/отмонтирования распространяются между mount namespace'ами. Управляется propagation flags.

**Peer group** — группа mount namespace'ов, обменивающихся событиями монтирования. Создаётся при флаге `shared`.

## Basic Concepts

### Propagation flags

| Флаг | Поведение | Направление |
| :--- | :--- | :--- |
| `MS_SHARED` | События распространяются на все namespace в peer group | Двустороннее |
| `MS_PRIVATE` | События не распространяются (по умолчанию для новых namespace) | Изолированное |
| `MS_SLAVE` | Получение событий от мастера без отправки обратно | Однонаправленное (мастер → подчинённый) |
| `MS_UNBINDABLE` | Запрет bind mount данной точки монтирования | — |

### Механизм наследования

При создании нового mount namespace через `clone(CLONE_NEWNS)` или `unshare --mount`:

1. Копируется таблица монтирования родительского namespace
2. Копируются propagation flags родительских точек монтирования
3. Дальнейшие изменения изолированы согласно флагам

### Таблица поведения propagation

| Флаг у Child | Mount в Parent | Mount в Child | Результат |
| :--- | :--- | :--- | :--- |
| **private** | `mount /dev/sdb1 /data` | — | Child не видит изменений |
| **private** | — | `mount /dev/sdc1 /mnt` | Parent не видит изменений |
| **shared** | `mount /dev/sdb1 /data` | — | Child получает `/data` |
| **shared** | — | `mount /dev/sdc1 /mnt` | Parent получает `/mnt` |
| **slave** | `mount /dev/sdb1 /data` | — | Child получает `/data` |
| **slave** | — | `mount /dev/sdc1 /mnt` | Parent **не видит** изменений |

## Practical Scenarios

### Изоляция в Docker

Docker использует mount namespace с propagation `private` по умолчанию:

- Файловая система контейнера изолирована от хоста
- Bind mounts (`-v`/`--mount`) — результат `mount --bind` из хоста в namespace контейнера
- Если исходная точка на хосте имеет `shared`, изменения могут распространяться в контейнер

### Управление propagation на хосте

```bash
# Сделать / и все подточки рекурсивно shared
mount --make-rshared /

# Сделать / рекурсивно private (изоляция)
mount --make-rprivate /

# Сделать / рекурсивно slave (одностороннее распространение от мастера)
mount --make-rslave /
```

**Практическое применение:** проброс монтируемых устройств (USB, диски) в работающие контейнеры требует настройки propagation на хосте и в контейнере.

### Диагностика mount namespace процесса

```bash
# Показать mount namespace процесса
ls -l /proc/<pid>/ns/mnt

# Сравнить mount namespace двух процессов
ls -l /proc/<pid1>/ns/mnt /proc/<pid2>/ns/mnt

# Просмотреть точки монтирования процесса
cat /proc/<pid>/mountinfo
```

## Additional Information

### Связанные концепции

- [Namespaces (общий обзор)](../Core/namespaces.md) — все типы namespaces
- [Изоляция в Linux: Namespaces и Cgroups](../../Docker/Concepts/linux_isolation.md) — применение в контейнеризации

### Системные вызовы

| Вызов | Назначение |
| :--- | :--- |
| `clone(CLONE_NEWNS, ...)` | Создание процесса в новом mount namespace |
| `unshare(CLONE_NEWNS)` | Отсоединение mount namespace текущего процесса |
| `setns(fd, CLONE_NEWNS)` | Присоединение к существующему mount namespace |
| `mount()` с `MS_*` флагами | Управление propagation точек монтирования |

### Историческая справка

Mount namespace (`CLONE_NEWNS`) — первый namespace, добавленный в ядро Linux 2.4.19 (2002 год). Остался единственным доступным механизмом контейнерной изоляции до появления остальных типов namespace в ядре 2.6.
