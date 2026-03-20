# OOM Killer Management

## Управление поведением OOM Killer

#### Для обычного процесса

Изменение `oom_score_adj` в реальном времени:

```bash
# Сделать процесс "неубиваемым" (максимальная защита)
sudo echo -1000 > /proc/<PID>/oom_score_adj

# Сделать процесс главным кандидатом на уничтожение
sudo echo 1000 > /proc/<PID>/oom_score_adj

# Просмотреть текущие значения
cat /proc/<PID>/oom_score
cat /proc/<PID>/oom_score_adj
```

> **Предупреждение:** Значение `-1000` не даёт 100% гарантии. При экстремальной нехватке памяти OOM Killer может всё равно выбрать этот процесс.

#### Для сервиса `systemd`

Используется директива в юнит-файле:

```ini
[Service]
OOMScoreAdjust=-1000
OOMPolicy=continue  # Продолжить работу сервиса после OOM
```

#### Для контейнеров Docker

```bash
# Запустить контейнер с изменённым oom_score_adj
docker run --oom-score-adj=500 nginx

# Запустить контейнер с отключённым OOM Killer
docker run --oom-kill-disable=true nginx
```

> **Важно:** `--oom-kill-disable` работает только вместе с `-m` (ограничение памяти).

---

**См. также:**

* [Механизм OOM Killer](./oom_killer_mechanism.md)
* [Диагностика OOM Killer](./oom_killer_diagnostics.md)
* [OOM Killer в контейнерах](./oom_killer_containers.md)
