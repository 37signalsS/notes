# Управление парком Runner'ов (Fleet Management)

## Определения

**Runner Fleet Management** — процесс централизованного управления группой GitLab Runner'ов, включающий мониторинг, масштабирование, обновление и оптимизацию использования ресурсов.

**Auto-scaling** — автоматическое создание и удаление Runner'ов в зависимости от нагрузки (очереди задач) для балансировки стоимости и производительности.

**Fleet Health** — совокупное состояние всех Runner'ов, определяемое доступностью, производительностью и использованием ресурсов.

## Теоретический блок

### Модели управления Runner'ами

| Модель | Описание | Использование | Стоимость |
|:---|:---|:---|:---|
| **Static (Shared)** | Постоянные серверы, всегда доступны | Малые команды, простые проекты | Фиксированная |
| **Auto-scaling (Docker Machine)** | Динамическое создание VM | Средние нагрузки | Pay-per-use |
| **Kubernetes Executor** | Поды в K8s кластере | Высокие нагрузки, K8s-native | Pay-per-use |
| **Fleeting/Taskscaler** | Нативный автоскейлинг через API | Enterprise, on-premise | Оптимальная |

### Архитектура Fleeting/Taskscaler

```
GitLab Server
    ↓ (очередь задач)
Taskscaler (планировщик)
    ↓ (запрос на инстанс)
Fleeting (менеджер инфраструктуры)
    ↓ (API вызовы)
    ├── OpenStack Nova
    ├── vSphere
    ├── Proxmox
    └── libvirt
```

### Метрики для принятия решений

| Метрика | Описание | Порог для масштабирования |
|:---|:---|:---|
| `pending_jobs` | Ожидающие задачи | > 5 в течение 5 минут |
| `runner_utilization` | Использование Runner'ов | > 80% в течение 10 минут |
| `queue_wait_time` | Время ожидания в очереди | > 3 минуты |
| `active_runners` | Активные Runner'ы | < 20% от максимального |
| `disk_usage` | Использование диска | > 85% |
| `memory_usage` | Использование памяти | > 90% |

### Стратегии масштабирования

| Стратегия | Описание | Когда использовать |
|:---|:---|:---|
| **Reactive** | Создание Runner'а при появлении задачи | Нерегулярные нагрузки |
| **Scheduled** | Создание Runner'ов по расписанию | Предсказуемые нагрузки (ночные сборки) |
| **Predictive** | На основе исторических данных | Крупные команды с трендами |
| **Hybrid** | Комбинация reactive + scheduled | Большинство production сред |

## Практический блок

### Мониторинг Runner fleet через API

```bash
#!/bin/bash
# runner_fleet_status.sh — проверка состояния всех Runner'ов

TOKEN="$GITLAB_API_TOKEN"
GITLAB_URL="https://gitlab.example.com"

echo "=== Runner Fleet Status ==="

# Получение списка всех Runner'ов
RUNNERS=$(curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
  "$GITLAB_URL/api/v4/runners?per_page=100" | jq '.')

# Статистика
TOTAL=$(echo "$RUNNERS" | jq 'length')
ACTIVE=$(echo "$RUNNERS" | jq '[.[] | select(.active == true)] | length')
ONLINE=$(echo "$RUNNERS" | jq '[.[] | select(.online == true)] | length')
PAUSED=$(echo "$RUNNERS" | jq '[.[] | select(.paused == true)] | length')

echo "Total Runners: $TOTAL"
echo "Active: $ACTIVE"
echo "Online: $ONLINE"
echo "Paused: $PAUSED"

# Детали по каждому Runner
echo ""
echo "=== Runner Details ==="
echo "$RUNNERS" | jq -r '.[] | "\(.id) |\(.description) |\(.status) |\(.active) |\(.jobs_completed) jobs completed"'

# Проверка проблемных Runner'ов
echo ""
echo "=== Problematic Runners ==="
echo "$RUNNERS" | jq -r '.[] | select(.online == false and .active == true) | "⚠️ \(.description) is offline but active"'
```

### Автоматическая очистка Docker контейнеров

```yaml
# .gitlab-ci.yml — очистка Runner'ов
runner:cleanup:
  stage: .pre
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  script:
    - |
      echo "=== Docker Cleanup ==="
      
      # Удаление остановленных контейнеров
      docker container prune -f
      echo "Pruned stopped containers"
      
      # Удаление неиспользуемых образов старше 7 дней
      docker image prune -a -f --filter "until=168h"
      echo "Pruned images older than 7 days"
      
      # Удаление неиспользуемых volumes
      docker volume prune -f
      echo "Pruned unused volumes"
      
      # Удаление build cache старше 7 дней
      docker builder prune -a -f --filter "until=168h"
      echo "Pruned build cache"
      
      # Статистика
      echo "=== Disk Usage After Cleanup ==="
      docker system df
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### Конфигурация config.toml для высокой нагрузки

```toml
# /etc/gitlab-runner/config.toml — оптимизированный для production
concurrent = 50
check_interval = 1
shutdown_timeout = 30

[session_server]
  session_timeout = 1800
  session_affinity = true

# Метрики для мониторинга
metrics_server = ":9252"

[[runners]]
  name = "high-performance-runner"
  url = "https://gitlab.example.com"
  token = "glrt-xxxxxxxxxxxx"
  executor = "docker"
  shell = "bash"
  
  # Лимиты задач
  limit = 10
  max_concurrent = 10
  
  # Очистка
  clean_policy = "always"
  clean_period = "24h"
  
  [runners.docker]
    image = "alpine:latest"
    privileged = false
    disable_entrypoint_overwrite = false
    oom_kill_disable = false
    disable_cache = false
    volumes = ["/cache", "/tmp/artifacts:/tmp/artifacts"]
    shm_size = 268435456  # 256 MB
    pull_policy = ["if-not-present"]
    
    # Лимиты ресурсов
    memory = "8g"
    cpus = "4"
    
    # Сеть
    dns = ["8.8.8.8", "8.8.4.4"]
    dns_search = []
    
    # Безопасность
    disable_sysctls = false
    security_opt = ["no-new-privileges"]
    
  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      ServerAddress = "minio.internal:9000"
      BucketName = "runner-cache"
      AccessKey = "${MINIO_ACCESS_KEY}"
      SecretKey = "${MINIO_SECRET_KEY}"
      Insecure = false
    [runners.cache.gcs]
      BucketName = ""
    [runners.cache.azure]
      AccountName = ""
      AccountKey = ""
      ContainerName = ""
```

### Автоматическое масштабирование через Terraform

```hcl
# terraform/runner-autoscaling.tf
resource "aws_launch_template" "gitlab_runner" {
  name_prefix   = "gitlab-runner-"
  image_id      = data.aws_ami.ubuntu.id
  instance_type = "m5.xlarge"

  user_data = base64encode(templatefile("${path.module}/runner-userdata.sh", {
    gitlab_url    = var.gitlab_url
    runner_token  = var.runner_token
    runner_tags   = ["docker", "linux", "auto-scale"]
    concurrent    = 5
  }))

  tagSpecifications {
    resource_type = "instance"
    tags = {
      Name        = "gitlab-runner"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

resource "aws_autoscaling_group" "gitlab_runners" {
  name                = "gitlab-runners-asg"
  min_size            = 1
  max_size            = 10
  desired_capacity    = 2
  vpc_zone_identifier = var.subnet_ids
  health_check_type   = "EC2"

  launch_template {
    id      = aws_launch_template.gitlab_runner.id
    version = "$Latest"
  }

  # Масштабирование по нагрузке
  scaling_policies {
    name                   = "scale-on-queue"
    policy_type            = "TargetTrackingScaling"
    target_tracking_configuration {
      predefined_metric_specification {
        predefined_metric_type = "ASGAverageCPUUtilization"
      }
      target_value = 70.0
    }
  }
}

# CloudWatch алерт на очередь задач
resource "aws_cloudwatch_metric_alarm" "runner_queue" {
  alarm_name          = "gitlab-runner-queue-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "PendingJobs"
  namespace           = "GitLab/Runner"
  period              = "300"
  statistic           = "Average"
  threshold           = "5"
  alarm_description   = "Runner queue is high"
  alarm_actions       = [aws_autoscaling_group.gitlab_runners.arn]
}
```

### Скрипт диагностики Runner'ов

```bash
#!/bin/bash
# runner_diagnostics.sh — полная диагностика Runner fleet

echo "=== GitLab Runner Diagnostics ==="

# 1. Статус службы
echo "1. Service Status:"
sudo gitlab-runner status

# 2. Версия
echo ""
echo "2. Version:"
sudo gitlab-runner --version

# 3. Зарегистрированные Runner'ы
echo ""
echo "3. Registered Runners:"
sudo gitlab-runner list

# 4. Проверка доступности
echo ""
echo "4. Runner Verification:"
sudo gitlab-runner verify

# 5. Системные ресурсы
echo ""
echo "5. System Resources:"
echo "   CPU: $(nproc) cores"
echo "   Memory: $(free -h | awk '/^Mem:/ {print $2}')"
echo "   Disk: $(df -h / | awk 'NR==2 {print $4}') available"
echo "   Load: $(uptime | awk -F'load average:' '{print $2}')"

# 6. Docker статус
echo ""
echo "6. Docker Status:"
if command -v docker &> /dev/null; then
    echo "   Docker version: $(docker --version)"
    echo "   Containers: $(docker ps -a | wc -l)"
    echo "   Images: $(docker images | wc -l)"
    echo "   Disk usage:"
    docker system df
else
    echo "   Docker not installed"
fi

# 7. Последние логи
echo ""
echo "7. Recent Logs (last 20 lines):"
sudo journalctl -u gitlab-runner --no-pager -n 20 2>/dev/null || echo "   No systemd logs available"

# 8. Проверка сети
echo ""
echo "8. Network Connectivity:"
if curl -s -o /dev/null -w "%{http_code}" "https://gitlab.example.com/api/v4/version" | grep -q "200"; then
    echo "   GitLab: ✓ Accessible"
else
    echo "   GitLab: ✗ Not accessible"
fi
```

## Дополнительная информация

### Связанные темы
- **[Обзор Runner и Executor](./gitlab_ci_runners_executors.md)** — типы Runner'ов и настройка
- **[Регистрация Runner](../Tutorials/runner_registration.md)** — установка и регистрация
- **[Мониторинг](./monitoring_and_metrics.md)** — метрики Runner'ов
- **[Кэширование](./gitlab_ci_caching/caching_overview.md)** — оптимизация кэша на Runner'ах
- **[Docker Compose установка](../Tutorials/gitlab_runner_docker_compose.md)** — запуск в контейнере

### Рекомендации по масштабированию
- Начинайте с shared runners, переходите на dedicated при росте нагрузки
- Настройте auto-scaling для предсказуемых нагрузок
- Регулярно очищайте Docker контейнеры и образы
- Мониторьте очередь задач и время ожидания
- Используйте tags для маршрутизации задач на appropriate runners
- Тестируйте failover regularly
