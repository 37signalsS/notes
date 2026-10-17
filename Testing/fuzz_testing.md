# Фаззинг-тестирование (Fuzz Testing)

**Актуально для:** AFL++ 4.x / libFuzzer (Clang 18+) / Go 1.23+ / Jazzer 0.2.x

## Определения

**Fuzzing (фаззинг)** — техника поиска уязвимостей и ошибок путем подачи приложению большого количества специально сгенерированных входных данных («мусорных»/edge-данных) и наблюдения за падениями, сбоями, зависаниями, ассертами или неопределённым поведением. В отличие от юнит-тестов проверяет не ожидаемое поведение, а **отсутствие непредсказуемого поведения**.

**Fuzzer** — инструмент/рантайт, генерирующий и передающий входные данные программе. Внутри фаззера — **генератор** (создаёт новые входы) и **мутатор** (изменяет существующие).

**Coverage-guided fuzzing** — разновидность, при которой генерация новых входов направляется на покрытие новых путей исполнения (анализ покрытия веток/instrumentation), — самый эффективный современный класс.

**Feedback-driven fuzzing** — обобщение coverage-guided: использует не только покрытие, но и другие сигналы (execution time, memory usage, sanitizer output).

**Black-box fuzzing** — без доступа к исходному коду; работает только с бинарником и входными данными. Менее эффективен, но применим к проприетарному ПО.

**White-box (concolic) fuzzing** — использует символьное выполнение (constraint solving) для покрытия путей. Пример: KLEE. Высокая точность, но экспоненциальная сложность.

**Corpus / Input corpus** — стартовый набор семплов, от которого фаззер размножает мутации. Seed corpus = начальные валидные примеры; regression corpus = найденные краши для воспроизведения.

**Crash (баг)** — найденный сбой; **Triage** — классификация/минимизация крэша (причина, регрессия, severity). **Minimize** — процесс уменьшения крэш-входа до минимального воспроизводимого.

**Sanitizer** — компиляторный проход (ASan, UBSan, MSan, TSan), обнаруждающий undefined behavior, out-of-bounds, data races и т.п. в ходе фаззинга.

**Harness** — тонкая граница между fuzzer и тестируемой функцией: функция, принимающая `[]byte` (или `uint8*`) и вызывающая тестируемый код.

**Mutation-based fuzzing** — мутирует существующие входы (bit flips, dictionary substitutions, splice). Основной подход для coverage-guided.

**Generation-based fuzzing** — генерирует входы с нуля по грамматике/формату (менее распространён, но эффективен для протоколов).

**Dictionary** — набор «интересных» токенов, которые fuzzer использует при мутировании (например, `HTTP/1.1`, JSON-ключи).

**Dictionary-guided fuzzing** — мутирование с применением dictionary-токенов для увеличения вероятности покрытия новых путей.

## Архитектура и принцип работы

### Как работает coverage-guided fuzzing

Цикл:

1. Фаззер берёт вход из seed-корпуса (или мутирует существующий).
2. Запускает целевую функцию с этим входом; инструментация собирает покрытие (edge/branch).
3. Если новый вход покрыл новый путь — он добавляется в корпус.
4. При сбое (crash, assertion, sanitizer-ошибка) вход сохраняется в `crash`-файл.
5. Цикл повторяется, постепенно расширяя покрытие до глубоких веток.

**Sanitizers** — решающий компонент: ASan (AddressSanitizer) ловит утечки/out-of-bounds, UBSan — undefined behavior, MSan — uninitialized, TSan — data races. Реально с корпусом фаззера работают в связке: «фаззер находит интересные входы → sanitizer превращает их в детектируемые сбои».

### Модель: изолированный harness

Фаззинг требует разъединения тестируемой функции от I/O (файлы, сеть, БД). Harness принимает сырые `[]byte` и делегирует логику в функции, которые не зависят от внешнего состояния:

```cpp
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // data — сырые байты; size — длина
    // НЕ: fopen, network, global state
    parse_config(data, size);
    return 0;  // 0 = no crash; non-zero = error to sanitizer
}
```

### Инструменты и их классификация

| Инструмент | Языки | Особенности |
| :--- | :--- | :--- |
| **libFuzzer** | C/C++/Rust | Встроен в Clang/LLVM; in-process, очень быстрый; интеграция с OSS-Fuzz |
| **AFL / AFL++** | C/C++ и др. | Самая популярная автономная связка; QEMU-mode, dumb mode, libFuzzer-взаимодействие |
| **Honggfuzz** | C/C++/Go и др. | Перспективный движок, поддержка ptrace, hardware feedback (Intel PT, ARM PMU) |
| **Jazzer** | Java | Про JVM; через Java native interface и JVM-instrumentation |
| **go-fuzz** / `go test -fuzz` | Go | Встроен в Go 1.18+; режим `-fuzz` в `testing` package |
| **OSS-Fuzz** | Любые | Сервис Google: continuous fuzzing в CI; регулярно находил сверхкритичных багов |
| **ClusterFuzz** | Любые | Инфраструктура continuous fuzzing от Google (используется OSS-Fuzz) |
| **Peach** | универсальный | Генерация-based; грамматико-ориентированный, для протоколов |
| **AFL++ LLVM deferred** | C/C++ | Улучшенная инструментация через `AFL_LLVM_DEFERRED=1` для больших программ |

### Где фаззить

- парсеры (JSON/XML/протоколы/файлы) — самое популярное;
- сетевые протоколы и веб-API (интерфейсы HTTP);
- шифрование/криптоподписи (демонстрация DoS/утечек);
- обработчики миграций/конфигураций (YAML/K8s);
- десериализация (protobuf/Thrift/MessagePack).

Слои: **unit-level** (функция с рандомным входом), **API-level** (через REST/gRPC), **protocol-level** (материалы контейнеров/пакетов).

### Единичный пример (libFuzzer + C++)

```cpp
#include <cstdint>
#include <cstddef>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  // ваша парс-функция
  parse_config(data, size);
  return 0;
}
```

Запуск:

```bash
clang++ -fsanitize=fuzzer,address -g fuzz_parse.cpp -o fuzzer
./fuzzer -max_len=4096 -runs=100000 corpus/
```

### Fuzzing как часть CI/Security-цикла

Три практики:

1. **Regression corpus**: после найденного крэша обязательно добавить вход в корпус и юнит-тест — ловить регрессию.
2. **Continuous fuzzing** (OSS-Fuzz, ClusterFuzz) — новый код попадает в continuous фаззера автоматом. Требует публичного репозитория и security-координаты.
3. **CI-gating**: короткие фаззин-прогоны (1–3 мин) на смену/PR ещё до мердж-конфликта — раннее обнаружение деградации.

Для частных/локальных CI используйте локальные фаззеры (AFL++, libFuzzer, go test -fuzz) с фиксированным seed и time-limited прогонами. OSS-Fuzz/ClusterFuzz применимы только к open-source проектам.

### Метрики и качество фаззинга

- **exec/sec** — скорость выполнения на вход;
- **coverage** — быстрорастущее покрытие (первичная метрика качества фаззера);
- **crashes/time** — число найденных багов;
- **unique crashes** — после минимизации.

## Практические сценарии

### Сценарий 1: Быстрый старт с libFuzzer (Clang)

**Prerequisites:** Clang 18+, компилятор с поддержкой `-fsanitize=fuzzer`.

```bash
clang++ -fsanitize=fuzzer,address -std=c++17 \
  -o my_fuzzer fuzz_target.cpp
mkdir -p corpus crashes
./my_fuzzer corpus/ -artifact_prefix=crashes/ -max_total_time=60
```

Найденный крэш: файл `crashes/<sha>`. Прогнать минимизацию: `-minimize_crash=1`.

**Валидация:**

```bash
ls crashes/                    # → crash-... файл
./my_fuzzer crashes/crash-*    # → reproduced, non-zero exit
```

### Сценарий 2: AFL++ (автономный)

**Prerequisites:** AFL++ 4.x, `afl-clang-fast` в `$PATH`.

```bash
afl-clang-fast -fsanitize=address -g target.c -o target
afl-fuzz -i in/ -o out/ -- ./target @@
# обзор: afl-whatsup out/  |  список крэшей в out/crashes/
```

**Валидация:**

```bash
afl-whatsup -c out/        # → 12 crashes, 4 unique
ls out/crashes/            # → id:000000...
```

### Сценарий 3: go-fuzz / go test -fuzz

**Prerequisites:** Go 1.23+, харнесс-функция в `*_test.go`.

```go
func FuzzParse(data []byte) {
    res, err := Parse(data)
    if err == nil && res == nil {
        panic("успешный парс без результата")
    }
}
```

```bash
go test -fuzz=FuzzParse -fuzztime=30s
```

**Валидация:**

```bash
grep "Failing" testdata/fuzz/FuzzParse/*  # → corpus entry that caused failure
```

### Сценарий 4: Jazzer (Java)

**Prerequisites:** Jazzer 0.2.x, JUnit 5+.

```java
@FuzzTest
void fuzzParser(byte[] data) {
    try {
        new ConfigParser().parse(data);
    } catch (ConfigException ignored) {}
}
```

```bash
jazzer --target_class=MyFuzzTarget corpus/ -max_total_time=60
```

**Валидация:**

```bash
ls corpus/  # → новые файлы из corpus
ls crashes/ # → reproduction files
```

### Сценарий 5: OSS-Fuzz интеграция (config)

**Prerequisites:** публичный репозиторий, security-контакт.

`project.yaml`:

```yaml
homepage: "https://example.com"
main_repo: "https://github.com/example/project.git"
primary_contact: "team@example.com"
auto_ccs:
- "security@example.com"
sanitizers:
- address
- undefined
```

После подключения инфраструктура сама строит фаззеры и аттачит отчёты о крэшах в issue-трекер проекта.

**Валидация:**

```bash
# Через 7–14 дней после merge в OSS-Fuzz:
curl https://oss-fuzz.com/  # → project registered, fuzzing active
```

### Сценарий 6: Интеграция в CI/CD (локальный go-fuzz)

**Prerequisites:** GitLab CI / GitHub Actions, Go 1.23+, `allow_failure: true` для flaky фаззинга.

```yaml
fuzz_testing:
  stage: test
  script:
    - go test -fuzz=FuzzParse -fuzztime=30s ./internal/parser
  allow_failure: true
```

**Валидация:**

```bash
# Pipeline passes even if fuzzer finds crash (non-blocking)
# Crash artifacts stored as job artifacts for triage
```

## Операции и команды

| Категория | Команда | Описание |
| :--- | :--- | :--- |
| Сборка fuzzer | `clang++ -fsanitize=fuzzer,address -g fuzz.cpp -o fuzzer` | libFuzzer + ASan |
| Запуск фаззинга | `./fuzzer corpus/ -max_total_time=60` | 60 секунд с corpus |
| Минимизация крэша | `./fuzzer -minimize_crash=1 crashes/crash-*` | Минимальный вход |
| AFL++ сборка | `afl-clang-fast -fsanitize=address target.c -o target` | Инструментация AFL |
| AFL++ запуск | `afl-fuzz -i in/ -o out/ -- ./target @@` | Запуск AFL++ |
| Go фаззинг | `go test -fuzz=FuzzParse -fuzztime=30s` | Встроенный go-fuzz |
| Jazzer | `jazzer --target_class=MyTarget corpus/` | Java fuzzer |
| Corpus seed | `echo '' > corpus/seed-empty` | Минимальный seed |
| Просмотр статистики | `afl-whatsup -c out/` | AFL++ crash summary |
| Просмотр покрытия | `llvm-profdata merge -sparse *.profraw` | Coverage data |
| Репродукция крэша | `./fuzzer crashes/crash-* -runs=1` | Воспроизведение |
| Остановка таймаутом | `-timeout=10` | 10s per single run |
| Memory limit | `-rss_limit_mb=2048` | 2GB RSS limit |

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| 0 exec/sec / fast-overflow | Неверная хар/омарка, отсутствие `@`-флага | Проверить аргументы AFL (`@@`), корректно указать перенаправление входа | Использовать AFL `argv` или stdin mode (`-__` для AFL) |
| Фаззер безпрогрессивен (нет новых покрытий) | Слабый корпус, «тупиковые» seed-ы | Проверить `-max_len`, corpus size | Расширить корпус валидными примерами; проверить seed corpus |
| Только OOM-крэши | Нет лимита памяти/времени | `dmesg` → `killed process`, `top` | `-rss_limit_mb`, `-timeout`; искать настоящие overflow |
| `AddressSanitizer: heap-buffer-overflow` | Реальный баг (не артефакт) | `gdb`, минимизация крэша | Минимизировать вход → воспроизвести → тикет |
| UBSan-шум от санитайзеров | Поведение включает UB по дизайну | Фильтр по stacktrace | Отключить конкретный checker (`-fsanitize=address` без `undefined`) |
| Сбои в CI / воспроизводимость | Фаззер недетерминиален (RNG) | Non-reproducible crash | Зафиксировать seed (`-seed=<N>`); проверить `-runs=0` с crash file |
| `LLVMFuzzerTestOneInput returned non-zero` | Harness вернул ошибку | Лог sanitizer + stacktrace | Исправить UB/issue в parse function; non-zero = crash signal |
| Corpus grows too large | Переполнение на disk | `du -sh corpus/` | Использовать `-max_len`, corpus merge |
| `error: '-fsanitize=fuzzer' runtime could not be satisfied` | Не Clang/LLVM | `clang++ --version` | Использовать `afl-clang-fast` или установить Clang |
| Fuzzer не находит новых путей | Harness слишком «узкий» (early return) | Coverage report (llvm-profdata) | Расширить grammar/dictionary; добавить dictionary-токены |
| Dictionary too aggressive | Мутирование ломает вход | Crash rate слишком высокий | Отключить `-dict` для проблемных файлов; настроить dictionary |

## Лучшие практики

- **Храните corpus в репо** — seed corpus в `corpus/`, regression corpus в `testdata/fuzz/`. Используйте `-artifact_prefix=` для consistency.
- **Фиксируйте seed в CI**: `-seed=<N>` гарантирует воспроизводимость.
- **CI-gating**: 1–3 минутные прогоны на PR с `allow_failure: true`; full fuzzing в nightly/separate job.
- **Минимизируйте крэши**: `-minimize_crash=1` перед тикетом — меньше corpus, быстрее reproduce.
- **Регрессионные тесты из крэшей**: добавляйте crash-вход как юнит-тест (assertion) — ловите регрессию.
- **Используйте dictionary**: для протоколов/языков — `-dict=proto.dict`, токены вроде `HTTP/`, `Content-Length`.
- **Ограничьте ресурсы**: `-rss_limit_mb=2048`, `-timeout=10` — фаззинг в CI не должен kill runner.
- **Coverage feedback** — используйте llvm-cov/Profdata для оценки эффективности corpus.
- **Не фаззите I/O напрямую**: вынесите network/file в harness через dependency injection (интерфейсы).

## Ограничения и крайние случаи

- **libFuzzer требует Clang/LLVM**: GCC не поддерживает `-fsanitize=fuzzer` (имеет только ASan/UBSan без fuzzer integration).
- **AFL++ в QEMU mode медленнее**: 10–100x slowdown vs.native; используйте только для black-box бинарей без исходников.
- **Jazzer работает только с JVM**: нативные библиотеки Java (через JNI) не fuzzer-ются напрямую.
- **OSS-Fuzz/ClusterFuzz только для open-source**: закрытые проекты должны использовать локальные фаззеры.
- **Coverage-guided не покрывает все**: side-channels (timing, cache) требуют дополнительных техник.
- **go test -fuzz требует Go 1.18+**: старые версии Go не поддерживают встроенный fuzz-раннер.
- **Фаззинг не заменяет security audits**: находит crash/UAF/UB, но не business-logic vulnerabilities.
- **Corpus explosion**: без `-max_len` и `-exact_ics` corpus растёт экспоненциально.
- **Non-determinism в multi-threaded коде**: используйте TSan (`-fsanitize=thread`) для выявления data races во время фаззинга.

## Очистка

- **Crash-артефакты**: удаляйте после triage `/ rm -rf crashes/`. Corpus сохраняйте.
- **AFL++ output**: `rm -rf out/` после прогона (может занимать ГБ).
- **Corpus cleanup**: `afl-cmin -i corpus/ -o corpus_min/` для уменьшения corpus.
- **Go fuzz cache**: `go clean -fuzzcache` — очистка кэша Go-фаззера.
- **Coverage artifacts**: `rm -f *.profraw *.profdata` после сбора метрик.
- **Docker volumes** (Testcontainers для API-уровня фаззинга): `docker volume prune -f`.
- **CI cleanup**: `after_script: - rm -rf corpus/ out/ crashes/ *.profraw` в CI-джобах.

## Дополнительная информация

### Связь с другими типами тестирования

Фаззинг дополняет классические типы тестирования — см. [Unit/Integration/E2E](./testing_types_unit_integration_e2e.md):
- **Unit** покрывают happy-path; фаззинг — edge/crash-кейсы.
- **Integration** проверяют workflow; фаззинг — adversarial данные в API-слое.
- **E2E** покрывают бизнес-сценарии; фаззинг — malformed request-ы на boundary.

Также связь с property-based testing (PBT) — [Schemathesis](../CI-CD/mobile-ci-cd/backend-integration-mobile.md), [Hypothesis (Python)](https://hypothesis.readthedocs.io/) (см. [TDD/BDD Overview](../CI-CD/Testing/tdd_bdd_overview.md)).

### Фаззинг и security testing

Фаззинг как техника security testing — см. [DAST Overview](../CI-CD/DevSecOps/dast_overview.md): fuzzing подходит к black-box и dynamic analysis, особенно для веб-API и протоколов.

### См. также

- **[Unit/Integration/E2E тестирование](./testing_types_unit_integration_e2e.md)** — где фаззинг дополняет классические тесты.
- **[DAST Overview](../CI-CD/DevSecOps/dast_overview.md)** — фаззинг в security-контуре.
- **[Testcontainers](./testcontainers_overview.md)** — для API-level fuzzing с реальными СУБД/сервисами.
- **[Управление тестовыми данными](./test_data_management.md)** — corpus и seed как материал фаззинга.
- **[Тестирование баз данных](./database_testing.md)** — property-based testing для SQL (SQLsmith).

### Внешние ресурсы

- [libFuzzer (LLVM)](https://llvm.org/docs/LibFuzzer.html) — официальная документация LLVM-фаззера.
- [AFL++](https://github.com/AFLplusplus/AFLplusplus) — продвинутый стек AFL++.
- [OSS-Fuzz](https://github.com/google/oss-fuzz) — сервис continuous fuzzing от Google.
- [ClusterFuzz](https://google.github.io/clusterfuzz/) — инфраструктура continuous fuzzing.