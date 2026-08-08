# Kubespray: Управление кластером

## Определения

**Управление кластером (Cluster Management)** — комплекс операций по изменению жизненного цикла существующего кластера Kubernetes: масштабирование, обновление версий, ротация сертификатов и вывод узлов из эксплуатации.

**Масштабирование (Scaling)** — изменение количества узлов. В Kubespray разделяется на добавление рабочих узлов (Workers) и узлов управления (Control Plane/etcd).

**Обновление (Upgrade)** — переход на новую версию Kubernetes. В Kubespray выполняется как автоматизированный процесс последовательного обновления (rolling update).

**Ротация сертификатов (Certificate Rotation)** — плановая замена TLS-сертификатов компонентов кластера до истечения их срока действия для обеспечения безопасности и непрерывности работы.

## Основные концепции

### Плейбуки жизненного цикла

После первичного развертывания для управления кластером используются специализированные сценарии:

| Плейбук | Назначение |
| :--- | :--- |
| **`scale.yml`** | Добавление новых рабочих узлов (Workers). |
| **`cluster.yml`** | Полная перенастройка или добавление узлов Control Plane / etcd. |
| **`upgrade-cluster.yml`** | Последовательное обновление всех компонентов (etcd, runtime, K8s). |
| **`remove-node.yml`** | Удаление узла: исключение из API, очистка конфигурации и остановка сервисов. |
| **`reset.yml`** | Полная очистка узлов от компонентов Kubernetes. |
| **`facts.yml`** | Сбор актуальных данных о состоянии узлов. |

### Правила и ограничения обновлений

1.  **Минорные версии:** поддерживается обновление только на одну минорную версию за раз (например, v1.34 → v1.35). Прямой переход v1.33 → v1.35 не поддерживается.
2.  **Состояние кластера:** перед началом любых операций все узлы должны быть в статусе `Ready`.
3.  **Кворум etcd:** обновление или добавление мастер-узлов критически зависит от доступности etcd. Рекомендуется иметь нечетное количество узлов etcd (3, 5).

## Практические сценарии

### 1. Масштабирование кластера

#### Добавление рабочих узлов (Worker Nodes)

Для ускорения процесса используйте флаг `--limit`.

1.  Добавьте новый хост в инвентарь (`inventory/mycluster/hosts.yaml`) в группу `kube_node`.
2.  Выполните запуск:
    ```bash
    ansible-playbook -i inventory/mycluster/hosts.yaml --become scale.yml --limit=new_node_name
    ```

#### Добавление узлов управления (Control Plane)

Добавление мастеров требует обновления конфигурации всего кластера для пересчета кворума и сертификатов.

1.  Добавьте хост в группы `kube_control_plane` и `etcd`.
2.  Выполните запуск (использование `--limit` не рекомендуется):
    ```bash
    ansible-playbook -i inventory/mycluster/hosts.yaml --become cluster.yml
    ```

### 2. Удаление узла

Плейбук выполняет `kubectl drain`, удаляет узел из API и очищает локальные данные.

```bash
ansible-playbook -i inventory/mycluster/hosts.yaml --become remove-node.yml -e node=node_name_to_remove
```

### 3. Обновление версии Kubernetes (v1.35)

#### Подготовка
- Создайте бэкап etcd. См. [Обслуживание etcd](../../Concepts/etcd_overview.md).
- Обновите локальный репозиторий Kubespray до нужной версии (например, ветка `branch-2.31` для K8s v1.35).

#### Выполнение
1. Укажите целевую версию в `group_vars/k8s_cluster/k8s-cluster.yml`:
   ```yaml
   kube_version: v1.35.4
   ```
2. Запустите обновление:
   ```bash
   ansible-playbook -i inventory/mycluster/hosts.yaml --become upgrade-cluster.yml
   ```

### 4. Ротация сертификатов

Если сертификаты истекают или скомпрометированы, их можно обновить без полного апгрейда кластера.

#### Плановая ротация через теги
```bash
ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml --tags=certificates,kubeadm
```

#### Ротация только сертификатов etcd
```bash
ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml --tags=etcd
```

#### Проверка срока действия
На любом мастере выполните:
```bash
kubeadm certs check-expiration
```

### 5. Полный сброс (Reset)

Используется для очистки узлов перед переиспользованием. **Внимание:** все данные будут удалены.

```bash
ansible-playbook -i inventory/mycluster/hosts.yaml --become reset.yml
```

## Диагностика и обслуживание

### Типовые проблемы

| Проблема | Решение |
| :--- | :--- |
| **Истекшие сертификаты** | Если Ansible не может подключиться из-за истечения срока, обновите сертификат на одном мастере вручную (`kubeadm certs renew all`), затем запустите Kubespray. |
| **Ошибка Drain** | Если поды не вытесняются, используйте `-e force_drain=true` (осторожно с данными без репликации). |
| **Развал кворума etcd** | Требуется восстановление из бэкапа. См. [Восстановление etcd](../../Concepts/etcd_overview.md). |

### Ручные операции (kubectl)

- `kubectl cordon <node>` — запрет на новые поды.
- `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` — подготовка к обслуживанию.
- `kubectl uncordon <node>` — возврат в планировщик.

## Дополнительная информация

### См. также
- **[Обзор Kubespray](./overview.md)** — архитектура и поддерживаемые компоненты.
- **[Установка: Определения](./kubespray_install/definitions.md)** — глоссарий терминов.
- **[etcd: Обзор](../../Concepts/etcd_overview.md)** — работа с хранилищем состояния.
- **[Траблшутинг Runtime](../../Troubleshooting/Common_Errors/NodeUnavailability/runtime_issues.md)** — диагностика containerd.

### Внешние ресурсы
- **[Kubespray: Upgrading Kubernetes](https://kubespray.io/#/docs/upgrades)** — официальное руководство.
- **[Kubeadm: Certificate Management](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/)** — подробности PKI.
