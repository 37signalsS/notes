# Автоматизация Kubernetes через Ansible

## Определения

- **`kubernetes.core`** — официальная и наиболее актуальная коллекция Ansible для взаимодействия с API Kubernetes. Она является правопреемником `community.kubernetes` и предоставляет декларативный интерфейс для управления ресурсами (Pod, Deployment, Service, CRD).
- **FQCN (Fully Qualified Collection Name)** — полное имя ресурса (например, `kubernetes.core.k8s`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен модулей и обеспечения стабильности плейбуков.
- **Server-Side Apply (SSA)** — современный механизм Kubernetes, переносящий логику слияния манифестов на сторону API-сервера. Это позволяет точнее управлять «владением» полями (Field Management) при работе нескольких контроллеров.
- **Python-клиент Kubernetes** — библиотека `kubernetes`, которую необходимо установить на **узле управления (Control Node)**. Модули Ansible работают как надстройка над этой библиотекой, поэтому их выполнение происходит локально, а взаимодействие с кластером идет по сети.

## Основные концепции

### Зависимости и подготовка

Для корректной работы коллекции на контрольном узле должны быть установлены следующие компоненты (рекомендуется использовать последние стабильные версии):

| Компонент | Назначение и требования |
| :--- | :--- |
| **`ansible`** | Метапакет версии 2.15+ (включает `kubernetes.core`). |
| **`python-kubernetes`** | Библиотека API (`pip install kubernetes`). Для SSA требуется версия 19.15.0+. |
| **`PyYAML`** | Для корректного парсинга YAML-манифестов. |
| **`jsonpatch`** | Необходим для выполнения патчей через модуль `k8s_json_patch`. |

### Ключевые модули

1.  **`kubernetes.core.k8s`**: Базовый модуль для управления любыми объектами Kubernetes. Поддерживает передачу манифеста в YAML, загрузку из внешних файлов или использование шаблонов Jinja2.
2.  **`kubernetes.core.helm`**: Управление Helm-чартами (установка, обновление, удаление релизов, управление репозиториями).
3.  **`kubernetes.core.k8s_info`**: Сбор информации о текущем состоянии ресурсов (аналог `kubectl get`). Незаменим для верификации состояния кластера.
4.  **`kubernetes.core.k8s_json_patch`**: Выполнение точечных изменений через RFC 6902 (когда стратегического слияния недостаточно).
5.  **`kubernetes.core.k8s_exec`**: Выполнение команд внутри контейнеров (аналог `kubectl exec`).
6.  **`kubernetes.core.k8s_log`**: Получение логов контейнеров для отладки или аудита.
7.  **`kubernetes.core.k8s_cp`**: Копирование файлов между локальной ФС и подами.

### Способы аутентификации

Ansible поддерживает гибкую настройку доступа к API кластера:
-   **Kubeconfig**: Использование файла конфигурации (по умолчанию `~/.kube/config`).
-   **Context**: Переключение между контекстами внутри одного или нескольких файлов конфигурации.
-   **API Key / Token**: Прямая аутентификация через токен (через параметры модуля или переменные окружения `K8S_AUTH_API_KEY`).
-   **Service Account**: Автоматическая настройка (In-cluster config), если Ansible сам запущен внутри пода Kubernetes.
-   **Переменные окружения**: Поддержка стандартных переменных `K8S_AUTH_*` для всех параметров подключения.

## Практические сценарии

### Сценарий 1: Развертывание приложения через шаблон Jinja2

Использование шаблонизации позволяет гибко управлять конфигурацией для разных сред (dev/prod).

```yaml
- name: Deploy Application with Jinja2 Template
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: "{{ app_name }}"
        namespace: default
      spec:
        replicas: "{{ replica_count }}"
        selector:
          matchLabels:
            app: "{{ app_name }}"
        template:
          metadata:
            labels:
              app: "{{ app_name }}"
          spec:
            containers:
            - name: main
              image: "{{ app_image }}:{{ app_version }}"
              ports:
              - containerPort: 80
```

### Сценарий 2: Управление Helm-чартом

Автоматизация установки сложных инфраструктурных компонентов.

```yaml
- name: Install Nginx Ingress Controller via Helm
  kubernetes.core.helm:
    name: ingress-nginx
    chart_ref: ingress-nginx/ingress-nginx
    release_namespace: ingress-nginx
    create_namespace: true
    values:
      controller:
        replicaCount: 3
        service:
          type: LoadBalancer
```

### Сценарий 3: Дожидание готовности ресурсов (Check & Wait)

Пример использования `k8s_info` для сложной логики ожидания в пайплайнах.

```yaml
- name: Wait for deployment to be ready
  kubernetes.core.k8s_info:
    kind: Deployment
    name: my-app
    namespace: prod
  register: deploy_info
  until: 
    - deploy_info.resources[0].status.readyReplicas is defined
    - deploy_info.resources[0].status.readyReplicas == deploy_info.resources[0].status.replicas
  retries: 20
  delay: 10
```
*Примечание: Современные версии модулей также поддерживают параметры `wait: yes` и `wait_condition` для упрощения этой задачи.*

### Сценарий 4: Применение Server-Side Apply (SSA)

Рекомендуется для бесконфликтного управления ресурсами, которые также могут модифицироваться внешними инструментами (например, Cloud-провайдерами или HPA).

```yaml
- name: Apply ConfigMap using SSA
  kubernetes.core.k8s:
    state: present
    server_side_apply:
      field_manager: ansible-controller
      force_conflicts: true
    definition:
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: app-config
        namespace: default
      data:
        key: value
```

### Сценарий 5: Динамический инвентарь из подов K8s

Использование плагина `kubernetes.core.k8s` для получения списка хостов из кластера.

```yaml
# inventory_k8s.yml
plugin: kubernetes.core.k8s
connections:
  - namespaces:
      - app-namespace
    labels:
      service: backend
```

## Дополнительная информация

### Сравнение с альтернативными инструментами

| Критерий | kubectl | Terraform | Ansible |
| :--- | :--- | :--- | :--- |
| **Стиль** | Императивный/Декларативный | Декларативный | Декларативный |
| **Управление состоянием** | etcd (внутри K8s) | State-файл (внешний) | etcd (внутри K8s) |
| **Сильные стороны** | Быстрая отладка | Жизненный цикл всей инфры | Оркестрация приложений и ОС |
| **Шаблонизация** | Ограничена (kustomize) | Нативная (HCL) | Мощная (Jinja2) |

### Рекомендации и лучшие практики

- **Идемпотентность**: Всегда используйте `state: present`. Ansible применит изменения только в том случае, если текущее состояние кластера отличается от описанного в плейбуке.
- **Безопасность (Vault)**: Никогда не храните пароли или секретные ключи в открытом виде. Используйте **Ansible Vault** для шифрования переменных, которые затем подставляются в `kind: Secret`.
- **Turbo Mode**: Для ускорения выполнения большого количества задач используйте плагин `cloud.common`, который удерживает постоянное соединение с API.
- **Проверка зависимостей**: Добавляйте предварительную задачу (`pre_tasks`) для проверки наличия Python-библиотеки `kubernetes` на контрольном узле.
- **Field Management**: При использовании SSA всегда задавайте уникальный `field_manager`, чтобы избежать конфликтов с ArgoCD или другими GitOps-инструментами.

### Смотрите также

- [Введение в Ansible](./ansible_introduction.md) — основы работы.
- [Helm: общие сведения](../Kubernetes/ToolsUtilities/Helm/helm_overview.md) — концепции пакетного менеджера.
- [Kubespray: автоматизация развертывания кластера](../Kubernetes/Installation/Kubespray/overview.md) — использование Ansible для установки K8s.
- [Динамический инвентарь в Ansible](./dynamic_inventory.md) — подробнее о плагинах инвентаризации.
