# Тестирование и валидация экспортеров Prometheus

## Определения

**Юнит-тестирование экспортера** — проверка отдельных функций коллектора (Collect, Describe) на изолированных входных данных без запуска HTTP-сервера или подключения к целевой системе. Основной инструмент в Go — библиотека `prometheus/testutil`, в Python — `prometheus_client.test`.

**Интеграционное тестирование экспортера** — проверка полного цикла: запуск HTTP-сервера, отправка запроса `/metrics`, валидация формата и значений метрик через `promtool check metrics` или парсинг вывода.

**Benchmarking экспортера** — измерение производительности экспортера под нагрузкой: время отклика при скрапинге, потребление CPU/memory, пропускная способность (метрик в секунду). Используется для принятия решения о масштабировании и поиска узких мест.

**Smoke-тест экспортера** — минимальная проверка работоспособности после развертывания: эндпоинт доступен, формат валиден, базовые метрики присутствуют.

**См. также:** [Создание собственных экспортеров](./custom_exporters.md), [Клиентские библиотеки](./client_libraries.md).

## Основные концепции

### Уровни тестирования

Тестирование экспортера分为四个 levels, каждый из которых проверяет свой аспект работоспособности:

| Уровень | Что проверяется | Инструменты | Когда запускать |
|:---|:---|:---|:---|
| **Юнит-тесты** | Логика Collect/Describe, обработка ошибок API, корректность значений | `prometheus/testutil` (Go), `prometheus_client.test` (Python) | При каждом коммите (CI) |
| **Интеграция** | Формат метрик, отсутствие дубликатов, корректность лейблов | `promtool check metrics`, HTTP-запрос к `/metrics` | При каждом PR |
| **Smoke** | Доступность эндпоинта, наличие метрики `up`, базовые значения | `curl`, `promtool check metrics` | После деплоя |
| **Benchmark** | Время отклика, CPU/memory, throughput | `go test -bench`, `wrk`/`hey`, `pprof` | Перед релизом, при оптимизации |

### Юнит-тесты в Go (prometheus/testutil)

Библиотека `prometheus/testutil` позволяет проверять, что коллектор возвращает ожидаемые метрики, без запуска HTTP-сервера.

**Установка:**
```go
import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/testutil"
)
```

**Базовый тест — проверка единственной метрики:**
```go
func TestMyCollector_UpMetric(t *testing.T) {
    collector := NewMyCollector(/* mock client */)

    // Ожидаемое значение
    expected := `
        # HELP myapp_external_system_up Статус доступности внешней системы
        # TYPE myapp_external_system_up gauge
        myapp_external_system_up 1
    `

    if err := testutil.CollectAndCompare(collector, expected); err != nil {
        t.Errorf("unexpected metrics:\n%s", err)
    }
}
```

**Тест с лейблами:**
```go
func TestMyCollector_LatencyMetric(t *testing.T) {
    collector := NewMyCollector(/* mock client returning 42.5 */)

    expected := `
        # HELP myapp_external_system_latency_seconds Задержка запросов к внешней системе
        # TYPE myapp_external_system_latency_seconds gauge
        myapp_external_system_latency_seconds{endpoint="default"} 42.5
    `

    if err := testutil.CollectAndCompare(collector, expected); err != nil {
        t.Errorf("unexpected metrics:\n%s", err)
    }
}
```

**Тест обработки ошибок (external system unavailable):**
```go
func TestMyCollector_ErrorHandling(t *testing.T) {
    // Мок-клиент, возвращающий ошибку
    mockClient := &MockExternalSystemClient{err: fmt.Errorf("connection refused")}
    collector := NewMyCollector(mockClient)

    expected := `
        # HELP myapp_external_system_up Статус доступности внешней системы
        # TYPE myapp_external_system_up gauge
        myapp_external_system_up 0
    `

    if err := testutil.CollectAndCompare(collector, expected); err != nil {
        t.Errorf("expected up=0 on error, got:\n%s", err)
    }
}
```

**Тест с фильтрацией метрик (когда тестируем только часть):**
```go
func TestMyCollector_OnlyUpMetric(t *testing.T) {
    collector := NewMyCollector(/* mock */)

    // Проверяем только up-метрику, игнорируя latency
    if err := testutil.CollectAndCompare(collector, expected,
        "myapp_external_system_up"); err != nil {
        t.Error(err)
    }
}
```

**Тест Counter с rate():**
```go
func TestInternalMetrics_ScrapeCount(t *testing.T) {
    internal := NewInternalMetricsCollector()

    // Имитируем 5 скрапингов
    for i := 0; i < 5; i++ {
        internal.Scrape()
    }

    expected := `
        # HELP myapp_exporter_scrapes_total Total number of scrapes.
        # TYPE myapp_exporter_scrapes_total counter
        myapp_exporter_scrapes_total 5
    `

    if err := testutil.CollectAndCompare(internal, expected); err != nil {
        t.Error(err)
    }
}
```

### Юнит-тесты в Python

Библиотека `prometheus_client` предоставляет утилиты для тестирования без HTTP-сервера.

```python
import pytest
from prometheus_client import CollectorRegistry, Gauge, Counter
from prometheus_client.test import TextCollectorMixin

class TestBackupCollector:
    def setup_method(self):
        self.registry = CollectorRegistry()

    def test_backup_up_on_success(self):
        """При успешном ответе backup_up должен быть 1"""
        # Имитация успешного ответа API
        collector = BackupCollector(
            backup_service_url="http://mock:8080",
            mock_response={"status": "ok", "last_success_timestamp": 1726512000}
        )
        self.registry.register(collector)

        metrics = list(collector.collect())
        up_metric = [m for m in metrics if m.name == 'myapp_backup_up'][0]
        assert up_metric.samples[0].value == 1

    def test_backup_up_on_error(self):
        """При ошибке API backup_up должен быть 0"""
        collector = BackupCollector(
            backup_service_url="http://unreachable:8080",
            mock_error=True
        )
        self.registry.register(collector)

        metrics = list(collector.collect())
        up_metric = [m for m in metrics if m.name == 'myapp_backup_up'][0]
        assert up_metric.samples[0].value == 0

    def test_error_counter_increments(self):
        """Счетчик ошибок должен инкрементироваться при сбоях"""
        collector = BackupCollector(
            backup_service_url="http://unreachable:8080",
            mock_error=True
        )
        self.registry.register(collector)

        # Вызываем collect 3 раза с ошибкой
        for _ in range(3):
            list(collector.collect())

        errors = [m for m in collector.collect() if m.name == 'myapp_backup_errors_total']
        assert errors[0].samples[0].value == 3
```

### Интеграционные тесты

Интеграционные тесты проверяют полный цикл: запуск экспортера, HTTP-запрос, валидация формата.

**Go — интеграционный тест с HTTP-сервером:**
```go
func TestExporter_Integration(t *testing.T) {
    collector := NewMyCollector(/* mock client */)
    prometheus.MustRegister(collector)

    // Запускаем HTTP-сервер на тестовом порту
    server := httptest.NewServer(promhttp.Handler())
    defer server.Close()

    // Отправляем запрос
    resp, err := http.Get(server.URL + "/metrics")
    if err != nil {
        t.Fatalf("failed to scrape: %v", err)
    }
    defer resp.Body.Close()

    // Проверяем HTTP-статус
    if resp.StatusCode != http.StatusOK {
        t.Errorf("expected 200, got %d", resp.StatusCode)
    }

    // Парсим и проверяем метрики
    var parser expfmt.TextParser
    families, err := parser.TextToMetricFamilies(resp.Body)
    if err != nil {
        t.Fatalf("failed to parse metrics: %v", err)
    }

    // Проверяем наличие ключевых метрик
    if _, ok := families["myapp_external_system_up"]; !ok {
        t.Error("missing metric: myapp_external_system_up")
    }

    up := families["myapp_external_system_up"].Metric[0].GetGauge().GetValue()
    if up != 1 {
        t.Errorf("expected up=1, got %f", up)
    }
}
```

**Bash — smoke-тест после деплоя:**
```bash
#!/bin/bash
set -euo pipefail

EXPORTER_URL="${1:-http://localhost:9101}"
ERRORS=0

echo "=== Smoke-тест экспортера: $EXPORTER_URL ==="

# 1. Доступность эндпоинта
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$EXPORTER_URL/metrics")
if [ "$HTTP_CODE" != "200" ]; then
    echo "FAIL: HTTP status $HTTP_CODE (ожидался 200)"
    ERRORS=$((ERRORS + 1))
else
    echo "OK: HTTP 200"
fi

# 2. Валидация формата
if ! curl -s "$EXPORTER_URL/metrics" | promtool check metrics > /dev/null 2>&1; then
    echo "FAIL: promtool check metrics не проходит"
    ERRORS=$((ERRORS + 1))
else
    echo "OK: формат валиден"
fi

# 3. Наличие HELP и TYPE
HELP_COUNT=$(curl -s "$EXPORTER_URL/metrics" | grep -c '^# HELP' || true)
TYPE_COUNT=$(curl -s "$EXPORTER_URL/metrics" | grep -c '^# TYPE' || true)
if [ "$HELP_COUNT" -eq 0 ] || [ "$TYPE_COUNT" -eq 0 ]; then
    echo "FAIL: отсутствуют HELP или TYPE строки"
    ERRORS=$((ERRORS + 1))
else
    echo "OK: HELP=$HELP_COUNT, TYPE=$TYPE_COUNT"
fi

# 4. Метрика up (если экспортер экспортирует)
UP_VALUE=$(curl -s "$EXPORTER_URL/metrics" | grep '^up' | awk '{print $2}' || true)
if [ -n "$UP_VALUE" ] && [ "$UP_VALUE" != "1" ]; then
    echo "FAIL: up=$UP_VALUE (ожидалось 1)"
    ERRORS=$((ERRORS + 1))
else
    echo "OK: up=$UP_VALUE"
fi

# 5. Отсутствие NaN/Inf (кроме stale markers)
NAN_COUNT=$(curl -s "$EXPORTER_URL/metrics" | grep -cE ' (NaN|Inf|-Inf)$' || true)
if [ "$NAN_COUNT" -gt 0 ]; then
    echo "WARN: обнаружено $NAN_COUNT значений NaN/Inf"
else
    echo "OK: NaN/Inf не обнаружены"
fi

echo "=== Результат: $ERRORS ошибок ==="
exit $ERRORS
```

### Benchmarking

**Go — бенчмарк производительности Collect():**
```go
func BenchmarkMyCollector_Collect(b *testing.B) {
    collector := NewMyCollector(/* mock fast client */)

    b.ResetTimer()
    for i := 0; i < b.N; i++ {
        ch := make(chan prometheus.Metric, 100)
        collector.Collect(ch)
        close(ch)
        // Прочитать все метрики из канала
        for range ch {
        }
    }
}

func BenchmarkMyCollector_CollectParallel(b *testing.B) {
    collector := NewMyCollector(/* mock fast client */)

    b.ResetTimer()
    b.RunParallel(func(pb *testing.PB) {
        for pb.Next() {
            ch := make(chan prometheus.Metric, 100)
            collector.Collect(ch)
            close(ch)
            for range ch {
            }
        }
    })
}
```

**Запуск бенчмарков:**
```bash
# Базовый бенчмарк
go test -bench=BenchmarkMyCollector -benchmem -count=3

# С профилированием CPU
go test -bench=BenchmarkMyCollector -benchmem -cpuprofile=cpu.prof

# С профилированием памяти
go test -bench=BenchmarkMyCollector -benchmem -memprofile=mem.prof

# Анализ профиля
go tool pprof cpu.prof
```

**Stress-тест через hey (HTTP-нагрузка):**
```bash
# 100 запросов в секунду в течение 30 секунд
hey -n 3000 -q 100 -c 10 http://localhost:9101/metrics

# С выводом гистограммы
hey -n 3000 -q 100 -c 10 -o csv http://localhost:9101/metrics > benchmark.csv
```

**Интерпретация результатов benchmarks:**

| Метрика | Норма | Тревога | Действие |
|:---|:---|:---|:---|
| `Collect()` latency | < 100ms | > 500ms | Оптимизировать API-запросы, кэширование |
| `Collect()` allocs/op | < 10 | > 100 | Снизить аллокации, переиспользовать буферы |
| HTTP scrape time | < 1s | > scrape_timeout | Увеличить scrape_timeout или оптимизировать |
| RSS при нагрузке | < 256MB | > 512MB | Проверить утечки памяти, уменьшить кэш |
| CPU при scrape | < 10% | > 50% | Фоновый опрос (Background Polling) вместо on-demand |

### CI/CD интеграция

**GitHub Actions — полный цикл тестирования:**
```yaml
name: Exporter CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: '1.24'

      - name: Юнит-тесты
        run: go test -v -race ./...

      - name: Бенчмарки
        run: go test -bench=. -benchmem -count=1 ./...

      - name: Сборка
        run: go build -o exporter .

      - name: Smoke-тест
        run: |
          ./exporter &
          sleep 2
          ./scripts/smoke-test.sh http://localhost:9101
          kill %1

      - name: Валидация формата
        run: |
          curl -s http://localhost:9101/metrics | promtool check metrics
```

**GitLab CI — аналогичный пайплайн:**
```yaml
test:
  stage: test
  image: golang:1.24
  script:
    - go test -v -race ./...
    - go test -bench=. -benchmem ./...
    - go build -o exporter .
    - ./exporter &
    - sleep 2
    - curl -s http://localhost:9101/metrics | promtool check metrics
    - kill %1
```

## Практические сценарии

### Сценарий 1: Тестирование экспортера с Background Polling

Экспортер кэширует данные в фоне. Юнит-тест должен проверить как начальное значение, так и обновление кэша.

```go
func TestBackgroundPollingExporter_CacheUpdate(t *testing.T) {
    mockClient := &MockClient{value: 100}
    collector := NewBackgroundExporter(mockClient, 1*time.Second)

    // Начальное значение (кэш пустой)
    ch := make(chan prometheus.Metric, 100)
    collector.Collect(ch)
    close(ch)

    // Ждем обновления кэша
    time.Sleep(2 * time.Second)

    // Проверяем обновленное значение
    ch2 := make(chan prometheus.Metric, 100)
    collector.Collect(ch2)
    close(ch2)

    metrics := collectMetrics(ch2)
    assertMetricValue(t, metrics, "myapp_cached_value", 100)
}
```

### Сценарий 2: Тестирование multi-target экспортера

```go
func TestMultiTargetExporter_DifferentTargets(t *testing.T) {
    targets := map[string]float64{
        "192.168.1.1": 1.0, // доступен
        "192.168.1.2": 0.0, // недоступен
    }

    for target, expectedUp := range targets {
        t.Run(target, func(t *testing.T) {
            collector := NewMultiTargetCollector(targets)

            expected := fmt.Sprintf(`
                # HELP myapp_target_up Статус цели
                # TYPE myapp_target_up gauge
                myapp_target_up{target="%s"} %.0f
            `, target, expectedUp)

            if err := testutil.CollectAndCompare(collector, expected,
                "myapp_target_up"); err != nil {
                t.Error(err)
            }
        })
    }
}
```

### Сценарий 3: Тестирование stale markers при shutdown

```go
func TestExporter_StaleMarkersOnShutdown(t *testing.T) {
    collector := NewMyCollector(/* mock */)

    // Эмулируем graceful shutdown
    collector.Shutdown()

    // После shutdown коллектор должен отправлять stale markers
    ch := make(chan prometheus.Metric, 100)
    collector.Collect(ch)
    close(ch)

    for metric := range ch {
        // Проверяем, что значение — stale NaN
        dto := &dto.Metric{}
        _ = metric.Write(dto)
        if !math.IsNaN(dto.GetGauge().GetValue()) {
            t.Error("expected stale NaN after shutdown")
        }
    }
}
```

### Сценарий 4: Интеграционный тест с promtool

```bash
#!/bin/bash
# integration-test.sh — полный интеграционный тест
set -euo pipefail

echo "=== Интеграционный тест экспортера ==="

# 1. Запуск экспортера
./exporter --config=test-config.yml &
EXPORTER_PID=$!
trap "kill $EXPORTER_PID 2>/dev/null" EXIT

sleep 3

# 2. Проверка доступности
echo "Проверка доступности..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:9101/metrics)
[ "$HTTP_CODE" = "200" ] || { echo "FAIL: HTTP $HTTP_CODE"; exit 1; }

# 3. Валидация формата через promtool
echo "Валидация формата..."
curl -s http://localhost:9101/metrics | promtool check metrics
echo "OK: формат валиден"

# 4. Проверка ожидаемых метрик
echo "Проверка метрик..."
METRICS=$(curl -s http://localhost:9101/metrics)

check_metric() {
    local metric_name=$1
    if echo "$METRICS" | grep -q "^$metric_name"; then
        echo "OK: $metric_name найдена"
    else
        echo "FAIL: $metric_name отсутствует"
        exit 1
    fi
}

check_metric "myapp_external_system_up"
check_metric "myapp_exporter_scrapes_total"
check_metric "myapp_exporter_scrape_duration_seconds"

# 5. Проверка значений (up должен быть 1 при работающей целевой системе)
UP_VALUE=$(echo "$METRICS" | grep '^myapp_external_system_up ' | awk '{print $2}')
[ "$UP_VALUE" = "1" ] || { echo "FAIL: up=$UP_VALUE"; exit 1; }

echo "=== Все проверки пройдены ==="
```

### Сценарий 5: Профилирование памяти экспортера

```bash
# Запуск экспортера с профилированием
./exporter &
PID=$!

# Сбор heap-профиля
go tool pprof -http=:8081 http://localhost:9101/debug/pprof/heap

# Анализ утечек памяти (pprof diff)
go tool pprof -top http://localhost:9101/debug/pprof/heap

# Проверка RSS vs Heap
cat /proc/$PID/status | grep -E 'VmRSS|VmSize'
```

## Дополнительная информация

### Чек-лист тестирования перед релизом

1. **Юнит-тесты покрывают happy path и error path** — Collect() корректно обрабатывает и успех, и ошибку API
2. **Юнит-тесты проверяют отсутствие panic** — нет `must`-вызовов, которые могут упасть при неожиданных данных
3. **Интеграционный тест проходит `promtool check metrics`** — нет дубликатов, корректные типы, `_total` суффиксы
4. **Smoke-тест после деплоя** — эндпоинт доступен, `up == 1`
5. **Benchmark не показывает регрессии** — latency Collect() не вырос > 20% от предыдущей версии
6. **Stale markers работают** — при shutdown метрики помечаются как устаревшие
7. **Нет high cardinality метрик** — количество уникальных лейблов стабильно при разных входных данных

### Типичные ошибки тестирования

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `duplicate metrics registration` в тесте | Реестр не очищается между тестами | Используйте `prometheus.NewRegistry()` в каждом тесте |
| `Collect() blocked` | Канал не читается | Убедитесь, что канал имеет достаточный буфер или читается в горутине |
| Race condition в тестах | Параллельный доступ к моку | Используйте `-race` флаг при `go test` |
| Benchmark показывает разные результаты | Фоновые процессы | Запускайте на чистой машине, `-count=5` для усреднения |
| Smoke-тест падает после деплоя | Экспортер не успел стартовать | Увеличьте `sleep` или добавьте readiness check |

### Матрица покрытия тестами

| Компонент | Юнит | Интеграция | Smoke | Benchmark |
|:---|:---:|:---:|:---:|:---:|
| Collector (Collect/Describe) | Обязательно | Обязательно | - | Рекомендуется |
| HTTP-эндпоинт /metrics | - | Обязательно | Обязательно | Рекомендуется |
| Обработка ошибок API | Обязательно | Рекомендуется | - | - |
| Stale markers | Рекомендуется | Рекомендуется | - | - |
| Native Histograms | Рекомендуется | Рекомендуется | - | - |
| TLS/Auth | - | Рекомендуется | Обязательно | - |
| Multi-target | Обязательно | Обязательно | - | Рекомендуется |

**См. также:**
- [Создание собственных экспортеров](./custom_exporters.md) — архитектурные паттерны и чек-лист SRE
- [Клиентские библиотеки](./client_libraries.md) — инструментация приложений
- [Textfile Collector](./textfile_collector.md) — простой сбор метрик из скриптов
- [Прометей — best practices](../../promtool_and_best_practices.md) — promtool и CI/CD
