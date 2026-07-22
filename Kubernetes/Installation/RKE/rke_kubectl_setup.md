# RKE: Установка kubectl и настройка доступа

## Определения

**kubectl** — CLI-утилита командной строки для управления кластером Kubernetes через API.

**kubeconfig** — YAML-файл конфигурации доступа к Kubernetes API. Содержит данные о кластерах, пользователях и контекстах.

**контекст** — логическая связка между кластером, пользователем и пространством имен по умолчанию.

## Базовые концепции

### Взаимодействие с RKE
Для управления кластером, развернутым через RKE, необходимо:
1. Установить утилиту `kubectl`.
2. Получить файл `kubeconfig` (из Rancher UI или через CLI после `rke up`).
3. Настроить контекст для работы с нужным кластером.

Подробная информация о структуре и механизмах слияния конфигов доступна в разделе **[Kubeconfig: Подключение к кластеру Kubernetes](../../Operations/kubeconfig_and_connection.md)**.

## Практические сценарии

### Шаг 1: Установка kubectl
Для установки `kubectl` на Linux, macOS или Windows воспользуйтесь единым руководством:
Инструкция по установке: [Установка kubectl](../kubectl_installation.md)

### Шаг 2: Получение kubeconfig из Rancher UI
Если RKE-кластер управляется через Rancher, выполните следующие действия:

1. **Открыть Rancher UI:**
   Перейдите по адресу вашего Rancher (например, `https://rancher.example.com`).

2. **Выбрать кластер:**
   - Перейдите в раздел `Cluster Management`.
   - Найдите нужный кластер в списке.

3. **Скачать конфигурацию:**
   - Нажмите на кнопку **Kubeconfig File** в верхней части панели управления кластером.
   - Скопируйте содержимое в буфер обмена или скачайте файл.

4. **Настроить локальный доступ:**
   ```bash
   # Создание директории (если отсутствует)
   mkdir -p $HOME/.kube
   
   # Сохранение конфигурации
   # Вставьте скопированный текст в файл
   nano $HOME/.kube/config 
   
   # Установка безопасных прав доступа
   chmod 600 $HOME/.kube/config
   ```

### Шаг 3: Проверка доступа
После настройки проверьте связь с кластером:

```bash
kubectl cluster-info
# → Kubernetes control plane is running at https://192.168.1.100:6443
# → CoreDNS is running at https://192.168.1.100:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

kubectl get nodes
# → NAME         STATUS   ROLES                      AGE   VERSION
# → node-01      Ready    controlplane,etcd,worker   10d   v1.30.2
# → node-02      Ready    worker                     10d   v1.30.2
```

### Работа с несколькими кластерами
Если вы управляете несколькими RKE-кластерами, используйте механизмы переключения контекстов:

```bash
# Просмотр доступных контекстов
kubectl config get-contexts
# → CURRENT   NAME            CLUSTER         AUTHINFO        NAMESPACE
# → *         rke-prod        rke-prod        user-abc12      default
# →           rke-dev         rke-dev         user-def34      dev

# Переключение на другой кластер
kubectl config use-context rke-dev
# → Switched to context "rke-dev".
```

## Дополнительная информация

**Безопасность:**
- Никогда не передавайте `kubeconfig` через открытые каналы связи (Slack, Telegram без шифрования).
- Используйте минимально необходимые права (RBAC) при создании конфигов для сторонних пользователей.

**См. также:**
- [RKE: Основные концепции](./rke_concepts.md)
- [RKE: Управление и поиск неисправностей](./rke_management_scenarios.md)
- [Kubeconfig: Подключение к кластеру Kubernetes](../../Operations/kubeconfig_and_connection.md)
