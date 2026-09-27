# Фаззинг-тестирование (Fuzz Testing)

## Определения

**Fuzzing (фаззинг)** — техника поиска уязвимостей и ошибок путём подачи приложению большого количества специально сгенерированных входных данных («мусорных»/edge-данных) и наблюдения за падениями, сбоями, зависаниями, ассертами или неопределённым поведением. В отличие от юнит-тестов проверяет не ожидаемое поведение, а **отсутствие непредсказуемого поведения**.

**Fuzzer** — инструмент/рантайм, генерирующий и передающий входные данные программе.

**Coverage-guided fuzzing** — разновидность, при которой генерация новых входов направляется на покрытие новых путей исполнения (анализ покрытия веток/instrucentation), — самый эффективный современный класс.

**Corpus / Input corpus** — стартовый набор семплов, от которого фаззер размножает мутации.

**Crash (баг)** — найденный сбой; **Triage** — классификация/минимизация крэша (причина, регрессия, severity).

## Основные концепции

### Как работает coverage-guided fuzzing

Цикл:

1. Фаззер берёт вход из seed-корпуса (или мутирует существующий).
2. Запускает целевую функцию с этим входом; инструментация собирает покрытия (edge/branch).
3. Если новый вход покрыл новый путь — он добавляется в корпус.
4. При сбое (crash, assertion, sanitizer-ошибка) вход сохраняется в `crash`-файл.
5. Цикл повторяется, постепенно расширяя покрытие до глубоких веток.

**Sanitizers** — решающий компонент: ASan (AddressSanitizer) ловит утечки/out-of-bounds, UBSan — undefined behavior, MSan — uninitialized. Реально с корпусом фаззера работают в связке: «фаззер находит интересные входы → sanitizer превращает их в детектируемые сбои».

### Часовые пояса (инструменты)

| Инструмент | Языки | Особенности |
| :--- | :--- | :--- |
| **libFuzzer** | C/C++/Rust | Встроен в Clang/LLVM; in-process, очень быстрый; интеграция с OSS-Fuzz |
| **AFL / AFL++** | C/C++ и др. | Самая популярная автономная связка; `QEMU`-mode, dumb mode, `libFuzzer`-взаимодействие |
| **Honggfuzz** | C/C++/Go и др. | Перспективный движок, поддержка ptrace, hardware feedback |
| **Jazzer** | Java | Про JVM; через Java native interface и JVM-instrumentation |
| **go-fuzz** | Go | Работа через IPv4-интерфейс, интеграция с `go test -fuzz` |
| **OSS-Fuzz** | Любые | Сервис Google: continuous fuzzing в CI; регулярно находил сверхкритичных багов |

### Ginommen b: где фаззить

- парсеры (JSON/XML/протоколы/файлы) — самое популярное;
- сетевые протоколы и веб-API (интерфейсы HTTP); 
- шифрование/криптоподписи (демонстрация DoS/утечек);
- обработчики миграций/конфигураций (YAML/K8s);

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
2. **Continuous fuzzing** (OSS-Fuzz, ClusterFuzz) — новый код попадает в облачный фаззера автоматов.
3. **CI-gating**: короткие фаззин-прогоны (1–3 мин) на смену/PR ещё до мердж-конфликта — раннее обнаружение деградации.

### Метрики и качество фаззинга

- **exec/sec** — скорость выполнения на вход;
- **coverage** — быстрорастущее покрытие (первичная метрика качества фаззера);
- **crashes/time** — число найденных багов;
- **unique crashes** — после минимизации.

## Практические сценарии

### Сценарий 1: Быстрый старт с libFuzzer (Clang)

```bash
clang++ -fsanitize=fuzzer,address -std=c++17 \
  -o my_fuzzer fuzz_target.cpp
mkdir -p corpus crashes
./my_fuzzer corpus/ -artifact_prefix=crashes/ -max_total_time=60
```

Найденный крэш: файл `crashes/<sha>`. Прогнать минимизацию: `-minimize_crash=1`.

### Сценарий 2: AFL++ (автономный)

```bash
afl-clang-fast -fsanitize=address -g target.c -o target
afl-fuzz -i in/ -o out/ -- ./target @@
# обзор: afl-whatsup out/  |  список крашей в out/crashes/
```

### Сценарий 3: go-fuzz / go test -fuzz

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

### Сценарий 4: Jazzer (Java)

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

### Сценарий 5: OSS-Fuzz интеграция (config)

`project.yaml` (context: репы в OSS-Fuzz):

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

После подключения инфраструктура сама строит фаззеры в облаке и аттачит отчёты о крэшах в issue-трекер проекта.

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| 0 exec/sec / fast-overflow | Неверная хар/омарка, отсутствие `@`-флага | Проверить аргументы AFL (`@@`), корректно указать перенаправление входа |
| Фаззер безпрогрессивен (нет новых покрытий) | Слабый корпус, «тупиковые» seed-ы | Расширить корпус валидными примерами; проверить `-max_len` |
| Только OOM-крэши | Нет лимита памяти/времени | `-rss_limit_mb`, `-timeout`; искать настоящие overflow |
| `AddressSanitizer: heap-buffer-overflow` | Реальный баг (не артефакт) | Минимизировать вход → воспроизвести → тикет |
| UBSan-шум от санитайзеров | Поведение включает UB по дизайну | Отключить конкретный checker, развести exprs |
| Сбои в CI / воспроизводимость | Фаззер недетерминиален (RNG) | Зафиксировать seed, `-seed`/флаги |

## Дополнительная информация

### См. также

- **[Unit/Integration/E2E тестирование](./testing_types_unit_integration_e2e.md)** — где фаззинг дополняет классические тесты.
- **[Безопасность и покрытие](../Security/README.md)** — вход фаззинга в security-контур (при наличии соответствующего каталога).
- **[Тестовые данные](./test_data_management.md)** — корпус и генерация входных данных как материал фаззинга.

### Внешние ресурсы

- [libFuzzer (LLVM)](https://llvm.org/docs/LibFuzzer.html) — официальная документация LLVM-фаззера.
- [AFL++](https://github.com/AFLplusplus/AFLplusplus) — продвинутый стек AFL++.
- [OSS-Fuzz](https://github.com/google/oss-fuzz) — сервис continuous fuzzing от Google.