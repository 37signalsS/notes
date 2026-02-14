# Управление версиями релизов

Управление версиями в Helm включает несколько взаимосвязанных уровней: версии самих чартов, версии приложения внутри чарта и ревизии релиза в кластере. Понимание этих сущностей позволяет воспроизводимо обновлять, откатывать и продвигать релизы через окружения.

## Типы версий в Helm

| Сущность | Где хранится | Формат | Назначение |
| :--- | :--- | :--- | :--- |
| Версия чарта | `Chart.yaml: version` | SemVer (например, 1.4.2) | Идентификация пакета Helm; влияет на выбор при установке/обновлении из репозитория. |
| Версия приложения | `Chart.yaml: appVersion` | Свободный (часто SemVer) | Маркер версии разворачиваемого софта; отображается в шаблонах, но не управляет поведением Helm. |
| Ревизия релиза | Secret/ConfigMap Helm в namespace релиза | Целое (1, 2, 3, …) | Снимок состояния релиза при каждой операции `upgrade`/`rollback`; используется для истории и откатов. |

Helm сохраняет историю релиза в Kubernetes-объектах с именованием вида `sh.helm.release.v1.<release-name>.v<revision>`. Это делает состояние аудируемым и воспроизводимым.

## История релиза и откаты

Каждый `helm upgrade` создает новую ревизию. Историю и детали изменений можно анализировать командами:

```bash
# Просмотр истории
helm history my-release -n prod

# Детали конкретной ревизии
helm get values my-release -n prod --revision 7
helm get manifest my-release -n prod --revision 7

Откат переключает релиз на ранее зафиксированную ревизию, сохраняя при этом новую запись истории:

```bash
helm rollback my-release 7 -n prod --wait --timeout 5m
```

### Зависимости

```yaml
# Chart.yaml
dependencies:
  - name: redis
    version: ^17.1.0
    repository: https://charts.bitnami.com/bitnami
```

```bash
# Обновление и фиксация
helm dependency update
# Создаёт Chart.lock с точными версиями
```

## Практические сценарии

### Установка конкретной версии

```bash
# Из репозитория
helm install myapp bitnami/nginx --version 13.2.0 -n prod

# Локальный чарт
helm install myapp ./mychart --atomic --history-max 20 -n prod
```

### Управление историей

```bash
# Ограничение глубины истории
helm upgrade myapp bitnami/nginx --history-max 10 -n prod

# Сохранение при удалении
helm uninstall myapp -n prod --keep-history

# Восстановление
helm rollback myapp 0 -n prod
```

### Продвижение через окружения

```bash
# Dev
helm upgrade --install app app-chart -f values/dev.yaml --version 2.3.1 -n dev

# Stage
helm upgrade --install app app-chart -f values/stage.yaml --version 2.3.1 -n stage

# Prod (фиксация версий)
helm upgrade --install app app-chart \
  -f values/prod.yaml \
  --version 2.3.1 \
  --wait --timeout 10m \
  --atomic -n prod
```

### Best practices

- **Пиннинг**: Явно указывать версии чартов
- **Атомарность**: Использовать `--atomic` и `--wait`
- **Контроль**: Хранить `values` в VCS
- **История**: Ограничивать `--history-max` для экономии ресурсов

## Дополнительная информация

- [Обзор Helm](./helm_overview.md) — общие концепции
- [Структура Helm-чарта](./helm_chart_structure.md) — метаданные в Chart.yaml
- [Сравнение Helm v2 и v3](./helm_v2_vs_v3.md) — различия в хранении
