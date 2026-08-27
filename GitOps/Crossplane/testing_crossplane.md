# Crossplane: Тестирование платформы

## Определения

**Тестирование композиций** — проверка того, что XRD/Composition/Functions генерируют корректные и ожидаемые ресурсы до применения в кластер. Критично, потому что одна Composition может породить десятки/сотни ресурсов с условиями и циклами.

**Render** — локальный прогон функций композиции (`crossplane composition render`) без Kubernetes-кластера, показывающий итоговые ресурсы («как `helm template`»).

**Validate** — проверка сгенерированных ресурсов по схемам провайдеров (`crossplane beta validate`).

**envtest / e2e** — интеграционные тесты против реального (или поднятого через envtest) API-сервера с реальными провайдерами.

## Базовые концепции

Пирамида тестирования платформы:
1. **Unit/Function-тесты** — логика кастомной функции (Go/Python) на уровне кода.
2. **Render-тесты** — детерминированный вывод Composition для заданного XR (быстро, без облака).
3. **Schema-валидация** — сгенерированные ресурсы соответствуют CRD провайдеров.
4. **e2e** — реальное применение Claim в тестовый кластер (kind) с провайдером в режиме `ObserveOnly`/fake.

«Сдвиг влево»: ловить ошибки композиции в CI, а не в проде.

## Практические сценарии

### 1. Render одной композиции (минимум три файла)
```bash
# xr.yaml — XR, composition.yaml — Composition (mode: Pipeline), functions.yaml — Function(ы)
crossplane composition render xr.yaml composition.yaml functions.yaml
```
Вывод — YAML-поток: сначала XR, затем сгенерированные composed-ресурсы.

### 2. Render с реальным состоянием и контекстом
```bash
# observed-resources — то, что уже есть в кластере (для status XR)
crossplane composition render xr.yaml composition.yaml functions.yaml \
  --observed-resources observed --include-full-xr

# extra-resources — EnvironmentConfig и прочие «внешние» ресурсы (функция environment-configs)
crossplane composition render xr.yaml composition.yaml functions.yaml \
  --extra-resources extra-resources --include-context
```
> Каждый observed-ресурс должен иметь аннотацию `crossplane.io/composition-resource-name`, совпадающую с именем ресурса в композиции.

### 3. Валидация по схемам провайдеров
```bash
crossplane composition render xr.yaml composition.yaml functions.yaml \
  | crossplane beta validate schemas -
```
Команда подтянет схемы из OCI-пакетов провайдеров и проверит, что вывод им соответствует.

### 4. Написание и локальная отладка кастомной функции (Python)
```yaml
# functions.yaml — запуск функции локально (Development runtime)
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-xbuckets
annotations:
  render.crossplane.io/runtime: Development
spec:
  package: xpkg.crossplane.io/negz/function-xbuckets:v0.1.0
```
При `Development` runtime `crossplane composition render` подключается к локально запущенной функции (`python .` / `go run .`) вместо Docker.

### 5. CI (GitHub Actions): render + validate на каждый PR
```yaml
name: composition-tests
on: [pull_request]
jobs:
  render:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: crossplane/action@v1        # устанавливает crossplane CLI
      - name: Render all compositions
        run: |
          for c in compositions/*.yaml; do
            crossplane composition render \
              test/xr.yaml "$c" test/functions.yaml \
              | crossplane beta validate schemas -
          done
```

### 6. Интеграционные тесты (envtest / kind)
Для проверки всей цепочки поднимите kind-кластер, установите Crossplane + провайдер(ы), примените XRD/Composition и Claim, затем дождитесь `Ready=True`. Upjet-провайдеры генерируют тесты против fake-клиента; для собственных композиций используйте `controller-runtime/envtest` и `crossplane alpha`/`crossplane beta test` (фреймворк тестирования композиций Upbound).

## Дополнительная информация

- [CLI: render / validate](https://docs.crossplane.io/latest/cli/command-reference/)
- [Написание функции на Python](https://docs.crossplane.io/latest/guides/write-a-composition-function-in-python/)
- Референсные примеры: репозиторий `upbound/composition-testing`.

Смежные темы:
- [Composition Functions и EnvironmentConfig](./composition_functions.md) — что и как рендерим.
- [Observability](./observability.md) — алерты на `Synced=False` после деплоя.
- [Обзор Crossplane](./overview.md).
