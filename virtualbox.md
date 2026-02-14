# Установка VirtualBox в Arch Linux

### Подготовка системы

1. **Полное обновление системы:**
    Выполните команду для обновления пакетов и системы. Это также установит последнюю версию ядра.

    ```bash
    sudo pacman -Syu
    ```

2. **Установка заголовков ядра:**
    Установите пакет `linux-headers`, соответствующий вашему ядру. Это критически важный шаг для корректной работы модулей `dkms`.

    ```bash
    sudo pacman -S --needed linux-headers
    ```

3. **Перезагрузка:**
    После обновления ядра рекомендуется перезагрузить систему, чтобы убедиться, что все изменения применились.

    ```bash
    sudo reboot
    ```

---

### Установка VirtualBox и модулей ядра

1. **Установка основных пакетов:**
    Эта команда установит VirtualBox и ISO-образ гостевых дополнений (Guest Additions), который понадобится для установки внутри виртуальных машин.

    ```bash
    sudo pacman -S virtualbox virtualbox-guest-iso
    ```

2. **Выбор модуля хоста:**
    Во время установки вам будет предложено выбрать пакет для `virtualbox-host-modules`. Рекомендуется выбрать `virtualbox-host-dkms`. Это позволит модулям VirtualBox автоматически пересобираться при каждом обновлении ядра, избавляя от необходимости делать это вручную.

---

### Настройка после установки

1. **Загрузка модулей ядра:**
    Загрузите модуль ядра VirtualBox. Это необходимо сделать один раз после установки.

    ```bash
    sudo modprobe vboxdrv
    ```

2. **Добавление пользователя в группу `vboxusers`:**
    Чтобы ваш пользователь мог управлять виртуальными машинами и использовать такие функции, как USB-устройства, его необходимо добавить в группу `vboxusers`.

    ```bash
    sudo gpasswd -a $USER vboxusers
    ```

    **Важно:** После выполнения этой команды необходимо **выйти из системы и снова войти**, чтобы изменения вступили в силу.

---

### Установка VirtualBox Extension Pack

**Extension Pack** расширяет функциональность VirtualBox, добавляя поддержку USB 2.0/3.0, шифрование дисков, загрузку по PXE и VirtualBox RDP (удаленный доступ к рабочему столу).

**Установка Extension Pack через `yay`:**
    Выполняйте команду от обычного пользователя (не от `root`). `yay` автоматически скачает последнюю версию Extension Pack, примет лицензионное соглашение и установит его.

```bash
yay -S virtualbox-ext-oracle
```

---

### Проверка установки

Чтобы убедиться, что модули ядра VirtualBox успешно загружены, выполните:

```bash
lsmod | grep vbox
```

Вы должны увидеть в выводе `vboxdrv` и другие связанные модули. После этого можно запускать VirtualBox и создавать виртуальные машины.









Kubernetes (53 файла):
- Autoscaling/: hpa_detailed.md, pod_disruption_budget.md, pod_distribution.md, scaling_patterns.md, vpa_detailed.md
- Base/: configmap.md, deployment.md, high_availability.md, secret.md, statefulset.md
- Base/Pod/: pod_labels_annotations_node_selection.md, pod_lifecycle_and_state.md
- Base/secrets/: creating_secrets.md, etcd_storage.md, external_managers.md, secrets_basics.md, security.md, using_secrets.md
- Concepts/: control_plane_architecture.md, etcd_overview.md, kubernetes_crd.md, kubernetes_operators.md
- Installation/Kubespray/additional_info_and_examples.md
- MonitoringLogging/EFK/: fluentbit_deep_dive.md, fluentbit/(buffering_routing.md, fluentbit_configuration.md, fluent_comparison.md, parsing.md, selection_criteria.md)
- Networking/Addons/metallb.md
- Networking/Network/cni_kube_proxy_roles.md
- Networking/Service/: service_overview.md, service_type_clusterip.md, service_type_loadbalancer.md, service_type_nodeport.md, service_types_summary.md
- Operations/: Advanced_Deployment_Strategies.md, node_maintenance.md
- Scheduling/: qos_limit_and_requests.md, taints_and_tolerations.md
- Security/: network_policies.md, pod_iam_irsa_kube2iam_kiam.md, sealed_secrets_overview.md
- Security/rbac/: aggregation_scenarios.md, bindings.md, limitations_opa.md, rbac_overview.md, roles.md
- Security/rbac_overview.md
- Storage/pv_and_pvc.md
- ToolsUtilities/Helm/: helm_chart_structure.md, helm_overview.md, helm_release_versioning.md, helm_templating.md, helm_v2_vs_v3.md
