# Lynis: Linux Security Auditing

## Definitions

**Lynis** ([CISOfy/lynis](https://github.com/CISOfy/lynis)) — инструмент аудита безопасности и проверки соответствия стандартам для Linux-систем. Выполняет сотни тестов для выявления уязвимостей и проблем конфигурации. Подробнее: [cisofy.com/lynis](https://cisofy.com/lynis/).

## Basic Concepts

Lynis проводит аудит системы по множеству категорий и предоставляет комплексную оценку безопасности.

### Что проверяет

- Настройки ядра и системные параметры
- Права доступа и аутентификация
- Конфигурации сетевых служб
- Наличие обновлений безопасности
- Соответствие стандартам CIS, NIST, HIPAA
- Логирование и мониторинг

### Анализ результатов

- **Hardening index** — оценка безопасности от 0 до 100
- **Warnings** — критичные проблемы
- **Suggestions** — рекомендации по улучшению
- **Detected software** — установленные пакеты и версии

## Practical Scenarios

### Базовый аудит системы

```bash
sudo lynis audit system
```

### Проверка конкретной группы тестов

```bash
# Проверка конфигураций SSH
sudo lynis audit system --tests-from-group ssh
```

### Расширенная проверка с отчётом

```bash
sudo lynis audit system --quick --nocolors --report-file /tmp/lynis-report.txt
```

### Проверка на соответствие стандарту

```bash
# Профиль CIS
sudo lynis audit system --profile cis
```

## Additional Information

### Автоматизация через Cron

Для регулярного аудита Lynis запускают через `cron` с опцией `--cronjob` (тихий режим, проверка всех категорий, вывод без спецсимволов):

```bash
# Ежедневный аудит в 22:30
30 22 * * * /path/to/lynis --cronjob audit system > /var/log/lynis-scan.log
```

### Пользовательские профили

Профили (`.prf`) позволяют создавать шаблоны для разных типов систем (веб-сервер, БД):

```bash
# Копирование стандартного профиля
cp default.prf my-custom.prf

# Запуск с кастомным профилем
lynis audit system --profile my-custom.prf
```

### Просмотр доступных тестов

```bash
lynis show tests
```

### Сравнение с другими инструментами

- **[kube-bench](../../Kubernetes/Security/kube-bench.md):** Аудит безопасности Kubernetes на CIS Benchmark. Lynis — аудит хостовых Linux-систем.
- **[docker-bench-security](../../Docker/Dockerfile/dockerfile_optimization_tools.md):** Аудит Docker-хостов на CIS Docker Benchmark. Lynis — общий аудит ОС.
