# Основные команды и рабочий процесс Helm

Полный жизненный цикл управления Helm-приложениями: от поиска чарта до установки, отладки и удаления.

---

## Definitions

| Термин | Описание |
|--------|----------|
| **Релиз** | Развёрнутый экземпляр чарта в Kubernetes-кластере. См. [Управление версиями релизов](./helm_release_versioning.md) |
| **helm upgrade --install** | Идемпотентная команда: устанавливает новый релиз или обновляет существующий |
| **helm template** | Локальный рендер шаблонов без обращения к кластеру. Ключевой инструмент отладки |
| **helm lint** | Валидация чарта на синтаксические ошибки и соответствие лучшим практикам |
| **helm rollback** | Откат релиза к предыдущей ревизии |

---

## Basic Concepts

### Идемпотентность развертывания

Команда `helm upgrade --install` устанавливает релиз, если он не существует, или обновляет существующий. Это обеспечивает предсказуемый результат при многократных вызовах, что критично для CI/CD.

### Атомарность обновлений

Helm гарантирует надежность развертываний с помощью флагов `--atomic` и `--timeout`. В случае сбоя (поды не переходят в состояние Ready), Helm автоматически откатывается к предыдущей стабильной версии.

---

## Practical Scenarios

### Управление приложениями: пример с kube-ops-view

* **Управление репозиториями**:
  * **Добавление**: `helm repo add stable https://charts.helm.sh/stable`
  * **Обновление**: `helm repo update`

* **Поиск чарта**:
  * **В Artifact Hub (глобальный поиск)**: `helm search hub kube-ops-view`
  * **В локальных репозиториях**: `helm search repo kube-ops-view`

* **Установка и кастомизация**:
    1. **Просмотр настроек**: `helm show values stable/kube-ops-view`
    2. **Кастомизация**: сохраните `values.yaml` для внесения изменений (`helm show values stable/kube-ops-view > values.yaml`).
    3. **Установка/Обновление**: примените изменения в кластере, используя `helm upgrade --install ops-view stable/kube-ops-view --namespace kube-system -f values.yaml --create-namespace --atomic`. Рекомендуется использовать плагин [helm-diff](./helm_plugins.md) для предпросмотра изменений.

* **Управление релизом**:
  * **Просмотр списка релизов**: `helm list -n kube-system`
  * **Проверка статуса релиза**: `helm status ops-view -n kube-system`
  * **Откат к предыдущей версии**: `helm rollback ops-view 1`
  * **Удаление релиза**: `helm uninstall ops-view -n kube-system`. **Важно**: удаляйте приложения только этой командой для корректного удаления всех связанных ресурсов (например, `ClusterRole`).

### Рабочий процесс разработки чарта

1. **Создание скелета чарта**:
    Команда `helm create <chart-name>` генерирует стандартную структуру директорий и файлов, включая `Chart.yaml`, `values.yaml` и примеры шаблонов.

    ```bash
    helm create my-chart
    ```

2. **Отладка и рендеринг шаблонов**:
    Команда `helm template` — ключевой инструмент разработчика. Рендерит шаблоны локально и выводит итоговые YAML-манифесты в консоль без обращения к кластеру.

    ```bash
    # Рендеринг с values по умолчанию
    helm template my-release ./my-chart

    # Рендеринг с кастомными values и выводом в файл
    helm template my-release ./my-chart -f my-values.yaml > rendered.yaml
    ```

3. **Переопределение `values.yaml`**:

    * **Файл со значениями (`-f` или `--values`)**: предпочтительный способ для множества изменений.

        ```bash
        helm install my-release ./my-chart -f my-values.yaml
        ```

    * **Прямое указание (`--set`)**: удобно для единичных изменений.

        ```bash
        helm install my-release ./my-chart --set replicaCount=5 --set image.tag="1.26.0"
        ```

4. **Валидация чарта**:

    ```bash
    helm lint ./my-chart
    ```

5. **Установка и удаление**:

    ```bash
    helm install my-release ./my-chart -n my-namespace --create-namespace
    helm uninstall my-release -n my-namespace
    ```

6. **Инспектирование локального чарта**:
    `helm pull stable/kube-ops-view --untar` скачивает и распаковывает архив чарта (`.tgz`) для локального изучения.

---

## Additional Information

Подробности о плагинах см. в [Helm Plugins](./helm_plugins.md). См. также [Практические сценарии чартов](./helm_chart_practical_scenarios.md) для production-рабочих процессов.
