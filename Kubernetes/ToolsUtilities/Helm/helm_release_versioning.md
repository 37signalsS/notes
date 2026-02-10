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
helm history my-release -n prod
helm status my-release -n prod
helm get values my-release -n prod --revision 7
helm get manifest my-release -n prod --revision 7
```

Откат переключает релиз на ранее зафиксированную ревизию, сохраняя при этом новую запись истории:

```bash
helm rollback my-release 7 -n prod --wait --timeout 5m
```

Релевантные практики:
*   Ограничивать глубину истории (`--history-max`) для экономии ресурсов.
*   Сохранять историю при удалении релиза (`--keep-history`), чтобы вернуть его при необходимости.

```bash
helm upgrade --install my-release repo/app --atomic --history-max 20 -n prod
helm uninstall my-release -n prod --keep-history
```

## Управление версиями чартов и зависимостей

Установка определенной версии чарта из репозитория:

```bash
helm repo add stable https://example.repo
helm install my-release stable/app --version 1.8.3 -n prod
```

Закрепление зависимостей выполняется через `Chart.yaml` с семантическими диапазонами версий и создание `Chart.lock` файла:

```yaml
# Chart.yaml (фрагмент)
dependencies:
  - name: redis
    version: ^17.1.0
    repository: https://charts.bitnami.com/bitnami
```

```bash
helm dependency update
# генерирует Chart.lock с точными версиями зависимостей
```

`Chart.lock` фиксирует конкретные артефакты, обеспечивая детерминированность сборки чарта в CI/CD.

## Стратегии обновления и фиксации

*   **Пиннинг версий:** Явно указывать версии чарта и зависимостей; использовать диапазоны с осторожностью.
*   **Атомарность:** Включать флаги `--wait` и `--atomic`, чтобы не оставить кластер в промежуточном состоянии.
*   **Контроль изменений значений:** Хранить `values` в VCS, сравнивать ревизии перед обновлением.

```bash
helm upgrade --install my-release stable/app \
  -f values/prod.yaml \
  --version 1.9.0 \
  --wait --timeout 10m --atomic -n prod
```

Продвижение через окружения (dev → stage → prod) обычно выполняется переиспользованием того же чарта и версии образов, меняя только конфигурацию:

```bash
# dev
helm upgrade --install app app-chart -f values/dev.yaml --version 2.3.1 -n dev

# stage
helm upgrade --install app app-chart -f values/stage.yaml --version 2.3.1 -n stage

# prod (после проверки)
helm upgrade --install app app-chart -f values/prod.yaml --version 2.3.1 -n prod
```

Такой подход фиксирует артефакты, а различия между окружениями выражаются в `values`, что упрощает аудит и воспроизводимость.
