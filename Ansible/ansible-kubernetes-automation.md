# Автоматизация Kubernetes через Ansible

## Определения

- **Ansible** — декларативный инструмент автоматизации, использующий push-модель и архитектуру без агентов (agentless). В контексте Kubernetes Ansible выполняет роль оркестратора, применяющего манифесты и управляющего ресурсами кластера через API.
- **Infrastructure as Code (IaC)** — подход к управлению инфраструктурой, при котором конфигурация серверов, сетей и сервисов описывается в машиночитаемых файлах (YAML, HCL). Ansible + Kubernetes реализуют IaC через декларативные YAML-манифесты.
- **`kubernetes.core`** — официальная и наиболее актуальная коллекция Ansible для взаимодействия с API Kubernetes. Она является правопреемником `community.kubernetes` и предоставляет декларативный интерфейс для управления ресурсами (Pod, Deployment, Service, CRD).
- **FQCN (Fully Qualified Collection Name)** — полное имя ресурса (например, `kubernetes.core.k8s`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен модулей и обеспечения стабильности плейбуков.
- **Server-Side Apply (SSA)** — современный механизм Kubernetes, переносящий логику слияния манифестов на сторону API-сервера. Это позволяет точнее управлять «владением» полями (Field Management) при работе нескольких контроллеров.
- **Custom Resource Definition (CRD)** — механизм расширения API Kubernetes, позволяющий создавать собственные ресурсы (например, `VirtualService`, `Certificate`, `ArgoRollout`). Ansible умеет работать с любыми CRD через `kubernetes.core.k8s`.
- **GitOps** — методология, при которой конфигурация кластера и приложений хранится в Git, а синхронизация состояния происходит автоматически через операторы (ArgoCD, Flux). Ansible дополняет GitOps, выполняя одноразовые задачи, не подходящие для декларативного пайплайна.
- **Python-клиент Kubernetes** — библиотека `kubernetes`, которую необходимо установить на **узле управления (Control Node)**. Модули Ansible работают как надстройка над этой библиотекой, поэтому их выполнение происходит локально, а взаимодействие с кластером идет по сети.
- **HPA (Horizontal Pod Autoscaler)** — контроллер масштабирования подов по потреблению ресурсов. Ansible может управлять HPA-объектами декларативно через те же модули `kubernetes.core.k8s`.

## Основные концепции

### Предварительные требования

Для корректной работы коллекции на контрольном узле должны быть установлены следующие компоненты:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **`ansible-core`** | 2.15+ | Ядро Ansible (рекомендуется 2.17+) |
| **`kubernetes.core`** | 3.2+ | Коллекция модулей для Kubernetes |
| **`python-kubernetes`** | 19.15.0+ | Python-клиент API (обязательно для SSA) |
| **`PyYAML`** | 6.0+ | Парсинг YAML-манифестов |
| **`jsonpatch`** | 1.16+ | Для `k8s_json_patch` (RFC 6902) |
| **`urllib3`** | 2.0+ | HTTP-клиент для REST API |
| **`requests`** | 2.28+ | HTTP-клиент (зависимость python-kubernetes) |

**Проверка окружения:**
```bash
# Проверка версий
python3 -c "import kubernetes; print(kubernetes.__version__)"
# → 29.0.0

ansible --version
# → ansible [core 2.17.x]

# Установка зависимостей
pip3 install 'kubernetes>=19.15.0' 'jsonpatch>=1.16' 'PyYAML>=6.0'

# Установка коллекции
ansible-galaxy collection install kubernetes.core
# → downloads to /Users/mac/.ansible/collections/ansible_collections/kubernetes/core
```

### Установка и настройка коллекции

**Способ 1: Standalone коллекция (рекомендуется)**
```bash
# Установка через requirements.yml
cat > requirements.yml << 'EOF'
collections:
  - name: kubernetes.core
    version: ">=3.2.0"
  - name: community.general
    version: ">=8.0.0"
EOF

ansible-galaxy collection install -r requirements.yml
```

**Способ 2: В составе Execution Environment**
```yaml
# execution-environment.yml
---
version: 3
build_arg_defaults:
  EE_BASE_IMAGE: quay.io/ansible/ansible-runner:latest
dependencies:
  galaxy:
    collections:
      - name: kubernetes.core
      - name: community.general
  python:
    - kubernetes
    - boto3
```

**Способ 3: Вirtualenv (изоляция)**
```bash
python3 -m venv ~/.venvs/ansible-k8s
source ~/.venvs/ansible-k8s/bin/activate
pip install ansible-core kubernetes jsonpatch PyYAML
ansible-galaxy collection install kubernetes.core
```

### Ключевые модули

| Модуль | Назначение | Аналог kubectl |
| :--- | :--- | :--- |
| **`kubernetes.core.k8s`** | Управление любыми объектами K8s (Deployments, Services, CRD, Namespace) | `kubectl apply` |
| **`kubernetes.core.k8s_info`** | Сбор информации о текущем состоянии ресурсов | `kubectl get` |
| **`kubernetes.core.helm`** | Управление Helm-чартами (установка, обновление, удаление релизов) | `helm install/upgrade/uninstall` |
| **`kubernetes.core.helm_repository`** | Управление репозиториями Helm | `helm repo add/remove/update` |
| **`kubernetes.core.helm_info`** | Получение информации о Helm-релизе | `helm list`, `helm status` |
| **`kubernetes.core.k8s_json_patch`** | Точечные изменения через RFC 6902 | `kubectl patch --type json` |
| **`kubernetes.core.k8s_exec`** | Выполнение команд внутри контейнеров | `kubectl exec` |
| **`kubernetes.core.k8s_log`** | Получение логов контейнеров | `kubectl logs` |
| **`kubernetes.core.k8s_cp`** | Копирование файлов между локальной ФС и подами | `kubectl cp` |
| **`kubernetes.core.k8s_scale`** | Масштабирование контроллеров (Deployment, StatefulSet) | `kubectl scale` |
| **`kubernetes.core.k8s_rollback`** | Откат к предыдущей версии Deployment | `kubectl rollout undo` |
| **`kubernetes.core.k8s_drain`** | Безопасный вывод узла из кластера (eviction подов) | `kubectl drain` |
| **`kubernetes.core.k8s_taint`** | Управление taints на узлах | `kubectl taint nodes` |

### Способы аутентификации

Ansible поддерживает гибкую настройку доступа к API кластера:

| Способ | Использование | Безопасность |
| :--- | :--- | :--- |
| **Kubeconfig** | Файл `~/.kube/config` (по умолчанию) | Файл на Control Node |
| **Context** | Выбор контекста из kubeconfig | Аналогично kubeconfig |
| **API Key / Token** | Прямая аутентификация через токен | Хранить в Vault |
| **Service Account** | In-cluster config (если Ansible в поде) | Автоматически |
| **Bearer Token** | Токен сервисного аккаунта | Хранить в Vault |
| **Переменные окружения** | `K8S_AUTH_*` | Файл на Control Node |

**Примеры аутентификации:**
```yaml
# Через kubeconfig
- name: Apply resource
  kubernetes.core.k8s:
    kubeconfig: ~/.kube/config
    context: minikube
    state: present
    definition:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: test-ns

# Через bearer token (для CI/CD)
- name: Apply resource
  kubernetes.core.k8s:
    host: https://k8s.example.com:6443
    api_key: "{{ vault_k8s_token }}"
    validate_certs: true
    state: present
    definition: "{{ lookup('template', 'deployment.yml.j2') }}"

# Через переменные окружения
# export K8S_AUTH_HOST=https://k8s.example.com:6443
# export K8S_AUTH_API_KEY=xxxx
# export K8S_AUTH_VERIFY_SSL=true
- name: Apply resource
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: my-config
      data:
        key: value
```

### Интеграция с Ansible Vault

Для безопасного хранения секретов, используемых в Kubernetes-манифестах:

```bash
# Шифрование файла переменных
ansible-vault encrypt vars/secrets.yml
# → Vault password: ___

# Создание зашифрованного файла
cat > vars/secrets.yml << 'EOF'
k8s_api_token: "eyJhbGciOiJSUzI1NiIs..."
k8s_namespace: "production"
db_password: "super_secret_123"
tls_cert: |
  -----BEGIN CERTIFICATE-----
  MIID...
  -----END CERTIFICATE-----
EOF

ansible-vault encrypt vars/secrets.yml
```

**Использование в плейбуке:**
```yaml
---
- name: Deploy with secrets
  hosts: localhost
  gather_facts: false
  vars_files:
    - vars/secrets.yml  # Зашифрованный файл
  tasks:
    - name: Create K8s Secret
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: v1
          kind: Secret
          metadata:
            name: app-secrets
            namespace: "{{ k8s_namespace }}"
          type: Opaque
          data:
            db-password: "{{ db_password | b64encode }}"
            tls.crt: "{{ tls_cert | b64encode }}"
```

## Практические сценарии

### Полный плейбук: развёртывание multi-tier приложения

Комплексный пример с Namespace, Deployment, Service, ConfigMap, Secret и Ingress:

```yaml
---
- name: Развёртывание Web-приложения в Kubernetes
  hosts: localhost
  gather_facts: false
  vars:
    app_name: myapp
    app_namespace: production
    app_image: nginx
    app_version: "1.25"
    replicas: 3
    db_host: postgresql.database.svc.cluster.local
    db_port: 5432

  tasks:
    # --- Namespace ---
    - name: Создание Namespace
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: v1
          kind: Namespace
          metadata:
            name: "{{ app_namespace }}"
            labels:
              app: "{{ app_name }}"
              environment: production

    # --- ConfigMap ---
    - name: Создание ConfigMap с конфигурацией приложения
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: v1
          kind: ConfigMap
          metadata:
            name: "{{ app_name }}-config"
            namespace: "{{ app_namespace }}"
          data:
            APP_ENV: "production"
            LOG_LEVEL: "info"
            DB_HOST: "{{ db_host }}"
            DB_PORT: "{{ db_port }}"
            NGINX_WORKER_PROCESSES: "auto"

    # --- Secret ---
    - name: Создание Secret с базой данных
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: v1
          kind: Secret
          metadata:
            name: "{{ app_name }}-secrets"
            namespace: "{{ app_namespace }}"
          type: Opaque
          data:
            db-password: "{{ db_password | b64encode }}"

    # --- Deployment ---
    - name: Создание Deployment
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: "{{ app_name }}"
            namespace: "{{ app_namespace }}"
            labels:
              app: "{{ app_name }}"
          spec:
            replicas: "{{ replicas }}"
            selector:
              matchLabels:
                app: "{{ app_name }}"
            strategy:
              type: RollingUpdate
              rollingUpdate:
                maxSurge: 1
                maxUnavailable: 0
            template:
              metadata:
                labels:
                  app: "{{ app_name }}"
                  version: "{{ app_version }}"
              spec:
                containers:
                  - name: web
                    image: "{{ app_image }}:{{ app_version }}"
                    ports:
                      - containerPort: 80
                    envFrom:
                      - configMapRef:
                          name: "{{ app_name }}-config"
                    env:
                      - name: DB_PASSWORD
                        valueFrom:
                          secretKeyRef:
                            name: "{{ app_name }}-secrets"
                            key: db-password
                    resources:
                      requests:
                        cpu: 100m
                        memory: 128Mi
                      limits:
                        cpu: 500m
                        memory: 512Mi
                    readinessProbe:
                      httpGet:
                        path: /
                        port: 80
                      initialDelaySeconds: 5
                      periodSeconds: 10
                    livenessProbe:
                      httpGet:
                        path: /
                        port: 80
                      initialDelaySeconds: 15
                      periodSeconds: 20

    # --- Service ---
    - name: Создание Service
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: v1
          kind: Service
          metadata:
            name: "{{ app_name }}-svc"
            namespace: "{{ app_namespace }}"
          spec:
            selector:
              app: "{{ app_name }}"
            ports:
              - port: 80
                targetPort: 80
            type: ClusterIP

    # --- Ingress ---
    - name: Создание Ingress
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: networking.k8s.io/v1
          kind: Ingress
          metadata:
            name: "{{ app_name }}-ingress"
            namespace: "{{ app_namespace }}"
            annotations:
              nginx.ingress.kubernetes.io/rewrite-target: /
          spec:
            ingressClassName: nginx
            rules:
              - host: "{{ app_name }}.example.com"
                http:
                  paths:
                    - path: /
                      pathType: Prefix
                      backend:
                        service:
                          name: "{{ app_name }}-svc"
                          port:
                            number: 80

    # --- HPA ---
    - name: Создание HPA (горизонтальное масштабирование)
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: autoscaling/v2
          kind: HorizontalPodAutoscaler
          metadata:
            name: "{{ app_name }}-hpa"
            namespace: "{{ app_namespace }}"
          spec:
            scaleTargetRef:
              apiVersion: apps/v1
              kind: Deployment
              name: "{{ app_name }}"
            minReplicas: 2
            maxReplicas: 10
            metrics:
              - type: Resource
                resource:
                  name: cpu
                  target:
                    type: Utilization
                    averageUtilization: 70

    # --- Верификация ---
    - name: Проверка доступности Deployment
      kubernetes.core.k8s_info:
        kind: Deployment
        name: "{{ app_name }}"
        namespace: "{{ app_namespace }}"
      register: deploy_status
      until:
        - deploy_status.resources[0].status.readyReplicas is defined
        - deploy_status.resources[0].status.readyReplicas == replicas
      retries: 30
      delay: 10

    - name: Проверка Service
      kubernetes.core.k8s_info:
        kind: Service
        name: "{{ app_name }}-svc"
        namespace: "{{ app_namespace }}"
      register: svc_status

    - name: Вывод информации о развёртывании
      ansible.builtin.debug:
        msg: >
          Приложение {{ app_name }} развёрнуто.
          Namespace: {{ app_namespace }},
          Ready replicas: {{ deploy_status.resources[0].status.readyReplicas }},
          ClusterIP: {{ svc_status.resources[0].spec.clusterIP }}
```

**Запуск и проверка:**
```bash
# Синтаксис и проверка
ansible-playbook deploy.yml --syntax-check
ansible-playbook deploy.yml --check --diff

# Запуск с зашифрованными переменными
ansible-playbook deploy.yml --ask-vault-pass -e "db_password=SuperSecret123"

# Запуск только Namespace + ConfigMap (теги)
ansible-playbook deploy.yml --tags "namespace,configmap"

# Проверка после развёртывания
kubectl get pods -n production -l app=myapp
kubectl get svc -n production
kubectl get ingress -n production
```

### Управление Helm-репозиториями и чартами

```yaml
---
- name: Управление Helm
  hosts: localhost
  gather_facts: false
  vars:
    helm_repos:
      - name: ingress-nginx
        url: https://kubernetes.github.io/ingress-nginx
      - name: jetstack
        url: https://charts.jetstack.io
      - name: prometheus-community
        url: https://prometheus-community.github.io/helm-charts

  tasks:
    # --- Репозитории ---
    - name: Добавление Helm-репозиториев
      kubernetes.core.helm_repository:
        name: "{{ item.name }}"
        repo_url: "{{ item.url }}"
      loop: "{{ helm_repos }}"

    - name: Обновление репозиториев
      kubernetes.core.helm:
        name: dummy
        chart_ref: stable/dummy
        state: absent
        update_repo_cache: true
      # Альтернатива: команда через module_shell
      ignore_errors: true

    # --- cert-manager ---
    - name: Установка cert-manager через Helm
      kubernetes.core.helm:
        name: cert-manager
        chart_ref: jetstack/cert-manager
        release_namespace: cert-manager
        create_namespace: true
        values:
          installCRDs: true
          replicaCount: 2
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 256Mi

    # --- Nginx Ingress ---
    - name: Установка Nginx Ingress Controller
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
            metrics:
              enabled: true

    # --- Prometheus Stack ---
    - name: Установка Prometheus Stack
      kubernetes.core.helm:
        name: kube-prometheus-stack
        chart_ref: prometheus-community/kube-prometheus-stack
        release_namespace: monitoring
        create_namespace: true
        values:
          grafana:
            enabled: true
            adminPassword: "{{ grafana_password | default('admin') }}"
          prometheus:
            prometheusSpec:
              retention: 15d
              storageSpec:
                volumeClaimTemplate:
                  spec:
                    accessModes: ["ReadWriteOnce"]
                    resources:
                      requests:
                        storage: 50Gi

    # --- Проверка установленных релизов ---
    - name: Получение списка Helm-релизов
      kubernetes.core.helm_info:
        name: cert-manager
        release_namespace: cert-manager
      register: cert_manager_info

    - name: Показать статус cert-manager
      ansible.builtin.debug:
        msg: >
          cert-manager: {{ cert_manager_info.status }}
          Версия чарта: {{ cert_manager_info.chart }}

    # --- Откат Helm-релиза ---
    - name: Откат ingress-nginx к предыдущей версии
      kubernetes.core.helm:
        name: ingress-nginx
        chart_ref: ingress-nginx/ingress-nginx
        release_namespace: ingress-nginx
        state: rolledback
        revision: 1  # Номер ревизии для отката
      when: rollback_ingress | default(false) | bool
```

### Удаление Helm-релизов

```yaml
- name: Удаление Helm-релиза
  kubernetes.core.helm:
    name: kube-prometheus-stack
    release_namespace: monitoring
    state: absent
```

### Управление Rbac и Service Account

```yaml
---
- name: Настройка RBAC
  hosts: localhost
  gather_facts: false
  vars:
    app_namespace: production
    app_name: myapp

  tasks:
    # --- Service Account ---
    - name: Создание ServiceAccount
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: v1
          kind: ServiceAccount
          metadata:
            name: "{{ app_name }}-sa"
            namespace: "{{ app_namespace }}"

    # --- Role (ограниченные права) ---
    - name: Создание Role для приложения
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: rbac.authorization.k8s.io/v1
          kind: Role
          metadata:
            name: "{{ app_name }}-role"
            namespace: "{{ app_namespace }}"
          rules:
            - apiGroups: [""]
              resources: ["configmaps", "secrets"]
              verbs: ["get", "list", "watch"]
            - apiGroups: [""]
              resources: ["pods"]
              verbs: ["get", "list"]

    # --- RoleBinding ---
    - name: Привязка Role к ServiceAccount
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: rbac.authorization.k8s.io/v1
          kind: RoleBinding
          metadata:
            name: "{{ app_name }}-binding"
            namespace: "{{ app_namespace }}"
          subjects:
            - kind: ServiceAccount
              name: "{{ app_name }}-sa"
              namespace: "{{ app_namespace }}"
          roleRef:
            kind: Role
            name: "{{ app_name }}-role"
            apiGroup: rbac.authorization.k8s.io

    # --- ClusterRole (глобальные права) ---
    - name: Создание ClusterRole для мониторинга
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: rbac.authorization.k8s.io/v1
          kind: ClusterRole
          metadata:
            name: "{{ app_name }}-clusterrole"
          rules:
            - apiGroups: [""]
              resources: ["nodes", "nodes/proxy"]
              verbs: ["get", "list", "watch"]
            - apiGroups: ["metrics.k8s.io"]
              resources: ["nodes", "pods"]
              verbs: ["get", "list"]
```

### Работа с CRD (Custom Resource Definitions)

```yaml
---
- name: Управление CRD и Custom Resources
  hosts: localhost
  gather_facts: false
  tasks:
    # --- Подтверждение CRD ---
    - name: Подтверждение CRD для Argo Rollouts
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: apiextensions.k8s.io/v1
          kind: CustomResourceDefinition
          metadata:
            name: rollouts.argoproj.io
          spec:
            group: argoproj.io
            names:
              kind: Rollout
              listKind: RolloutList
              plural: rollouts
              singular: rollout
            scope: Namespaced
            versions:
              - name: v1alpha1
                served: true
                storage: true
                schema:
                  openAPIV3Schema:
                    type: object
                    properties:
                      spec:
                        type: object
                        properties:
                          replicas:
                            type: integer
                          strategy:
                            type: object

    # --- Argo Rollout (кастомный ресурс) ---
    - name: Создание Argo Rollout
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: argoproj.io/v1alpha1
          kind: Rollout
          metadata:
            name: my-app-rollout
            namespace: production
          spec:
            replicas: 5
            strategy:
              canary:
                steps:
                  - setWeight: 20
                  - pause: {duration: 5m}
                  - setWeight: 40
                  - pause: {duration: 5m}
                  - setWeight: 60
                  - pause: {duration: 5m}
                  - setWeight: 80
                  - pause: {duration: 5m}
            selector:
              matchLabels:
                app: my-app
            template:
              metadata:
                labels:
                  app: my-app
              spec:
                containers:
                  - name: my-app
                    image: my-app:2.0.0
                    ports:
                      - containerPort: 8080

    # --- Информация о CRD ---
    - name: Получение информации о CRD
      kubernetes.core.k8s_info:
        kind: CustomResourceDefinition
        name: rollouts.argoproj.io
      register: crd_info

    - name: Показать версию CRD
      ansible.builtin.debug:
        msg: >
          CRD: {{ crd_info.resources[0].metadata.name }},
          API Versions: {{ crd_info.resources[0].spec.versions | map(attribute='name') | list }}
```

### Комплексное управление подами: exec, log, cp

```yaml
---
- name: Управление подами
  hosts: localhost
  gather_facts: false
  vars:
    target_namespace: production
    target_pod: my-app-7d4b8f6c9-x2jkl

  tasks:
    # --- Получение логов ---
    - name: Получение логов пода
      kubernetes.core.k8s_log:
        name: "{{ target_pod }}"
        namespace: "{{ target_namespace }}"
        container: web
        tail_lines: 100
      register: pod_logs

    - name: Сохранение логов в файл
      ansible.builtin.copy:
        content: "{{ pod_logs.log_lines | join('\n') }}"
        dest: "/tmp/{{ target_pod }}.log"
        mode: '0644'

    # --- Выполнение команды в поде ---
    - name: Проверка конфигурации Nginx
      kubernetes.core.k8s_exec:
        name: "{{ target_pod }}"
        namespace: "{{ target_namespace }}"
        container: web
        command: nginx -t
      register: nginx_test

    - name: Показать результат проверки
      ansible.builtin.debug:
        msg: >
          Exit code: {{ nginx_test.rc }},
          Stdout: {{ nginx_test.stdout }},
          Stderr: {{ nginx_test.stderr }}

    # --- Интерактивная команда ---
    - name: Получение информации о диске
      kubernetes.core.k8s_exec:
        name: "{{ target_pod }}"
        namespace: "{{ target_namespace }}"
        command: df -h /var/log
      register: disk_info

    - name: Показать информацию о диске
      ansible.builtin.debug:
        var: disk_info.stdout_lines

    # --- Копирование файлов в под ---
    - name: Копирование конфигурационного файла
      kubernetes.core.k8s_cp:
        name: "{{ target_pod }}"
        namespace: "{{ target_namespace }}"
        container: web
        remote_path: /etc/nginx/nginx.conf
        local_path: /tmp/nginx.conf
        state: to pod
      when: false  # Включить при необходимости

    # --- Копирование файлов из пода ---
    - name: Копирование логов из пода
      kubernetes.core.k8s_cp:
        name: "{{ target_pod }}"
        namespace: "{{ target_namespace }}"
        container: web
        remote_path: /var/log/nginx/access.log
        local_path: /tmp/access.log
        state: from pod
```

### Jinja2-шаблон для K8s манифестов

```jinja2
{# templates/deployment.yml.j2 — Полный шаблон для Deployment #}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ app_name }}
  namespace: {{ app_namespace | default('default') }}
  labels:
    app: {{ app_name }}
    environment: {{ app_environment | default('production') }}
    version: {{ app_version }}
    managed-by: ansible
  annotations:
    deployment.kubernetes.io/revision: "{{ deployment_revision | default('1') }}"
spec:
  replicas: {{ replica_count | default(3) }}
  selector:
    matchLabels:
      app: {{ app_name }}
  strategy:
    type: {{ strategy_type | default('RollingUpdate') }}
    {% if strategy_type | default('RollingUpdate') == 'RollingUpdate' %}
    rollingUpdate:
      maxSurge: {{ max_surge | default('25%') }}
      maxUnavailable: {{ max_unavailable | default('0') }}
    {% endif %}
  template:
    metadata:
      labels:
        app: {{ app_name }}
        version: {{ app_version }}
      annotations:
        prometheus.io/scrape: "{{ enable_prometheus | default('true') }}"
        prometheus.io/port: "{{ metrics_port | default('9090') }}"
    spec:
      serviceAccountName: {{ app_name }}-sa
      securityContext:
        runAsNonRoot: true
        fsGroup: 1000
      containers:
        - name: {{ app_name }}
          image: {{ app_image }}:{{ app_version }}
          imagePullPolicy: {{ image_pull_policy | default('IfNotPresent') }}
          ports:
            - name: http
              containerPort: {{ app_port | default(80) }}
              protocol: TCP
            {% if enable_metrics | default(false) %}
            - name: metrics
              containerPort: {{ metrics_port | default(9090) }}
              protocol: TCP
            {% endif %}
          envFrom:
            - configMapRef:
                name: {{ app_name }}-config
            {% if secrets_name is defined %}
            - secretRef:
                name: {{ secrets_name }}
            {% endif %}
          resources:
            requests:
              cpu: {{ cpu_request | default('100m') }}
              memory: {{ memory_request | default('128Mi') }}
            limits:
              cpu: {{ cpu_limit | default('500m') }}
              memory: {{ memory_limit | default('512Mi') }}
          readinessProbe:
            httpGet:
              path: {{ health_check_path | default('/health') }}
              port: http
            initialDelaySeconds: {{ readiness_delay | default(5) }}
            periodSeconds: {{ readiness_period | default(10) }}
          livenessProbe:
            httpGet:
              path: {{ health_check_path | default('/health') }}
              port: http
            initialDelaySeconds: {{ liveness_delay | default(15) }}
            periodSeconds: {{ liveness_period | default(20) }}
          {% if enable_volume | default(false) %}
          volumeMounts:
            - name: {{ volume_name | default('data') }}
              mountPath: {{ volume_mount_path | default('/data') }}
          {% endif %}
      {% if enable_volume | default(false) %}
      volumes:
        - name: {{ volume_name | default('data') }}
          persistentVolumeClaim:
            claimName: {{ pvc_name | default(app_name + '-pvc') }}
      {% endif %}
      {% if node_selector is defined %}
      nodeSelector:
        {% for key, value in node_selector.items() %}
        {{ key }}: "{{ value }}"
        {% endfor %}
      {% endif %}
      {% if tolerations is defined %}
      tolerations:
        {% for t in tolerations %}
        - key: "{{ t.key }}"
          operator: "{{ t.operator | default('Equal') }}"
          value: "{{ t.value }}"
          effect: "{{ t.effect }}"
        {% endfor %}
      {% endif %}
```

**Использование шаблона в плейбуке:**
```yaml
---
- name: Развёртывание через шаблон
  hosts: localhost
  gather_facts: false
  vars:
    app_name: webapp
    app_namespace: production
    app_image: nginx
    app_version: "1.25"
    replica_count: 3
    enable_prometheus: true
    enable_volume: true
    node_selector:
      disktype: ssd
      zone: us-east-1a
    tolerations:
      - key: "dedicated"
        value: "web"
        effect: "NoSchedule"

  tasks:
    - name: Развёртывание Deployment
      kubernetes.core.k8s:
        state: present
        definition: "{{ lookup('template', 'templates/deployment.yml.j2') }}"
```

### Динамический инвентарь из Kubernetes

```yaml
# inventory/k8s.yml — Плагин динамического инвентаря
---
plugin: kubernetes.core.k8s
connections:
  # Все поды в namespace с лейблом app=backend
  - namespaces:
      - production
    labels:
      app: backend

  # Поды в namespace staging
  - namespaces:
      - staging
    labels:
      app: frontend

  # Поды по аннотации
  - namespaces:
      - monitoring
    annotations:
      prometheus.io/scrape: "true"

# Настройки подключения
kubeconfig: ~/.kube/config
context: production-cluster

# Фильтрация только запущенных подов
restrict_pod_phase: Running

# Кэширование инвентаря
cache: true
cache_plugin: jsonfile
cache_timeout: 300
cache_connection: /tmp/k8s_inventory_cache

# Маппинг переменных
compose:
  ansible_host: "metadata.annotations['prometheus.io/host'] | default(status.podIP)"
  ansible_port: "metadata.annotations['prometheus.io/port'] | default(80)"
  ansible_user: "'deploy'"
```

**Проверка инвентаря:**
```bash
# Просмотр всех хостов
ansible-inventory -i inventory/k8s.yml --graph

# Просмотр переменных конкретного хоста
ansible-inventory -i inventory/k8s.yml --host my-app-pod-xyz

# Просмотр всей структуры
ansible-inventory -i inventory/k8s.yml --list | jq '._meta.hostvars'
```

### Тестирование через Molecule

```yaml
# molecule/default/molecule.yml
---
dependency:
  name: galaxy
driver:
  name: delegated
platforms:
  - name: k8s-test
provisioner:
  name: ansible
verifier:
  name: ansible
scenario:
  test_sequence:
    - dependency
    - cleanup
    - syntax
    - create
    - prepare
    - converge
    - idempotence
    - verify
    - destroy
```

```yaml
# molecule/default/converge.yml
---
- name: Converge
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Создание тестового Namespace
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: v1
          kind: Namespace
          metadata:
            name: molecule-test

    - name: Развёртывание тестового Deployment
      kubernetes.core.k8s:
        state: present
        definition:
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: test-app
            namespace: molecule-test
          spec:
            replicas: 1
            selector:
              matchLabels:
                app: test-app
            template:
              metadata:
                labels:
                  app: test-app
              spec:
                containers:
                  - name: nginx
                    image: nginx:alpine
                    ports:
                      - containerPort: 80
```

## Устранение типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `No module named 'kubernetes'` | Не установлена Python-библиотека | `pip3 install kubernetes` |
| `kubernetes.core.k8s: Failed to import the required library` | Библиотека не найдена в Python path | Проверьте `which python3` и `pip3 install kubernetes` |
| `Unable to connect to the server: x509: certificate` | Неверный сертификат или self-signed | `validate_certs: false` (для dev) или добавьте CA в trusts |
| `Error from server (NotFound): the server doesn't have a resource type` | CRD не установлен | Установите CRD перед использованием custom resources |
| `Error from server (Conflict): the object has been modified` | Конфликт при Server-Side Apply | Используйте `force_conflicts: true` в `server_side_apply` |
| `Error from server (Forbidden)` | Недостаточно прав RBAC | Проверьте Role/ClusterRole и RoleBinding |
| `helm: releasing "xxx" failed: cannot re-use a name that is still in use` | Релиз с таким именем уже существует | `state: present` → `state: latest` или `state: rolledback` |
| `Unable to connect to the server: connection refused` | K8s API недоступен | Проверьте `kubectl cluster-info`, сетевые настройки |
| `Error from server (Too Many Requests)` | Rate limiting API-сервера | Уменьшите параллелизм, используйте `wait: yes` |
| `k8s_exec: Timeout waiting for` | Под не готов или команда зависла | Проверьте readiness probe, используйте `timeout` параметр |

**Диагностика:**
```bash
# Проверка подключения к кластеру
kubectl cluster-info
kubectl get nodes

# Проверка плагина инвентаря
ansible-doc -t inventory kubernetes.core.k8s

# Просмотр переменных подключения
ansible localhost -m debug -a "var=ansible_facts"

# Тестирование с подробным выводом
ansible-playbook deploy.yml -vvv --check --diff
```

## Контрольный список: лучшие практики

- [ ] Используйте FQCN для всех модулей (`kubernetes.core.k8s` вместо `k8s`)
- [ ] Храните секреты в Ansible Vault, а не в открытом виде
- [ ] Всегда проверяйте плейбуки через `--check --diff` перед продакшеном
- [ ] Используйте `state: present` для идемпотентного применения
- [ ] Задавайте `resource requests` и `limits` для каждого контейнера
- [ ] Настройте readiness/liveness probes для всех приложений
- [ ] Используйте Server-Side Apply для ресурсов, управляемых несколькими контроллерами
- [ ] Устанавливайте CRD до использования custom resources
- [ ] Используйте `namespace` для изоляции окружений
- [ ] Тестируйте плейбуки через Molecule с драйвером `delegated`

## Дополнительная информация

- [Динамический инвентарь](./dynamic_inventory.md) — подробнее о плагинах инвентаризации (включая k8s).
- [Kubespray: автоматизация развёртывания кластера](../Kubernetes/Installation/Kubespray/overview.md) — Ansible для установки Kubernetes.
- [Ansible Vault](../Vault/overview.md) — безопасное хранение секретов.
