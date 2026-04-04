# OOM Killer Management

## Определения

**Управление OOM Killer** — настройка поведения механизма OOM Killer через корректировку рейтинга процессов (`oom_score_adj`), политики systemd (`OOMScoreAdjust`, `OOMPolicy`) и параметры контейнеров (`--oom-score-adj`, `--oom-kill-disable`). Цель — защитить критичные процессы и контролировать поведение системы при нехватке памяти.

## Основные концепции

### Механизмы управления

| Механизм | Область применения | Параметры |
| :--- | :--- | :--- |
| **`oom_score_adj`** | Отдельный процесс | `-1000` (макс. защита) … `1000` (макс. риск) |
| **systemd `OOMScoreAdjust`** | Сервис systemd | Аналогично `oom_score_adj` |
| **systemd `OOMPolicy`** | Сервис systemd | `continue`, `stop`, `restart` |
| **Docker `--oom-score-adj`** | Контейнер Docker | `-1000` … `1000` |
| **Docker `--oom-kill-disable`** | Контейнер Docker | Отключение OOM Killer (только с `-m`) |
| **cgroups `memory.oom.group`** | Группа процессов (v2) | Групповое завершение при OOM |

### Значения `oom_score_adj`

| Значение | Эффект | Когда использовать |
| :--- | :--- | :--- |
| **-1000** | Максимальная защита | Критичные системные процессы (ssh, systemd) |
| **-500…-1** | Повышенная защита | Базы данных, мониторы, orchestrator-ы |
| **0** | По умолчанию | Обычные процессы |
| **1…999** | Повышенный риск | Тестовые процессы, некритичные задачи |
| **1000** | Первый кандидат | Процессы, которые можно убить первыми |

> **Важно:** Значение `-1000` не дает 100% гарантии. При экстремальной нехватке памяти OOM Killer может всё равно выбрать этот процесс.

### Политика `OOMPolicy` в systemd

| Значение | Поведение | Когда использовать |
| :--- | :--- | :--- |
| **`continue`** | Игнорировать OOM, продолжить работу | Stateless сервисы, некритичные задачи |
| **`stop`** | Остановить сервис (не перезапускать) | Сервисы, требующие ручного вмешательства |
| **`restart`** | Перезапустить сервис (по `Restart=`) | Stateless сервисы с возможностью восстановления |

## Практические сценарии

### Для обычного процесса

```bash
# Сделать процесс "неубиваемым" (максимальная защита)
echo -1000 | sudo tee /proc/<PID>/oom_score_adj

# Сделать процесс главным кандидатом на уничтожение
echo 1000 | sudo tee /proc/<PID>/oom_score_adj

# Просмотреть текущие значения
cat /proc/<PID>/oom_score
cat /proc/<PID>/oom_score_adj
```

### Для сервиса `systemd`

```ini
# /etc/systemd/system/my-app.service
[Service]
OOMScoreAdjust=-500       # Повышенная защита
OOMPolicy=continue        # Продолжить работу после OOM
```

```bash
# Применить изменения
sudo systemctl daemon-reload && sudo systemctl restart my-app

# Проверить примененные значения
systemctl show my-app.service | grep OOM
```

### Для контейнеров Docker

```bash
# Запустить контейнер с повышенной защитой
docker run --oom-score-adj=-500 nginx

# Запустить контейнер с отключенным OOM Killer (с лимитом памяти)
docker run -m 512m --oom-kill-disable=true nginx
```

> **Важно:** `--oom-kill-disable` работает только вместе с `-m` (ограничение памяти). Без лимита контейнер может исчерпать всю память хоста.

### Для Kubernetes

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: critical-app
spec:
  containers:
  - name: app
    image: critical-app:latest
    resources:
      requests:
        memory: "512Mi"
      limits:
        memory: "1Gi"
```

> Kubernetes автоматически устанавливает `oom_score_adj` на основе QoS класса: `Guaranteed` → -998, `Burstable` → 2–999, `BestEffort` → 1000. Подробнее: [OOM Killer in Containers](./oom_killer_containers.md).

### Групповое завершение в cgroups v2

```bash
# Включить групповое завершение (все процессы в cgroup будут убиты одновременно)
echo 1 | sudo tee /sys/fs/cgroup/<path>/memory.oom.group

# Проверить настройку
cat /sys/fs/cgroup/<path>/memory.oom.group
```

## Дополнительная информация

### Безопасность и риски

- **`oom_score_adj=-1000`:** Не гарантирует защиту при экстремальной нехватке памяти
- **`--oom-kill-disable`:** Опасно без лимита памяти — может привести к зависанию хоста
- **`OOMPolicy=continue`:** Сервис продолжит работу, но может работать некорректно после OOM
- **Критичные процессы:** Всегда мониторьте потребление памяти (Prometheus, Grafana)

### Автоматизация управления OOM Score

Скрипт для批量ной настройки защиты процессов:

```bash
#!/bin/bash
# Установить oom_score_adj для процессов по имени
set_oom() {
    local name=$1
    local score=$2
    for pid in $(pgrep -f "$name"); do
        echo "Setting oom_score_adj=$score for $name (PID: $pid)"
        echo $score | sudo tee /proc/$pid/oom_score_adj
    done
}

# Примеры использования
set_oom "nginx" -500
set_oom "postgres" -800
set_oom "redis" -700
```

### Рекомендации по выбору стратегии

| Сценарий | Рекомендуемое значение | Обоснование |
| :--- | :--- | :--- |
| **База данных (PostgreSQL, MySQL)** | `-800…-500` | Потеря данных при OOM недопустима |
| **Web-сервер (nginx, apache)** | `-500…-200` | Критичен для доступности |
| **Приложение (Java, Python)** | `0` | Стандартное поведение |
| **Worker-процессы (celery, rq)** | `200…500` | Можно перезапустить без потери данных |
| **Тестовые/debug процессы** | `800…1000` | Первые кандидаты на удаление |

---

Механизм работы OOM Killer описан в [**OOM Killer Mechanism**](./oom_killer_mechanism.md). Диагностика — в [**OOM Killer Diagnostics**](./oom_killer_diagnostics.md). Поведение в контейнерах — в [**OOM Killer in Containers**](./oom_killer_containers.md).
