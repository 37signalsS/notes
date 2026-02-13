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















Kafka (4 файла):
- delivery_guarantees.md, message_queues_principles.md, partitioning_and_balancing.md, rabbitmq_vs_kafka.md
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
- Security/iam/: best_practices.md, irsa.md, kube2iam_kiam.md, pod_iam_overview.md
- Security/: network_policies.md, pod_iam_irsa_kube2iam_kiam.md, sealed_secrets_overview.md
- Security/rbac/: aggregation_scenarios.md, bindings.md, limitations_opa.md, rbac_overview.md, roles.md
- Security/rbac_overview.md
- Storage/pv_and_pvc.md
- ToolsUtilities/Helm/: helm_chart_structure.md, helm_overview.md, helm_release_versioning.md, helm_templating.md, helm_v2_vs_v3.md
Linux (18 файлов):
- Core/: firmware_bios_uefi.md, kernel/boot_process.md
- Diagnostics/Networking/: dns_diagnostics.md, ss.md
- FileSystems/mounting/: additional_info.md, commands.md, fstab.md, index.md, mounting.md, scenarios/(autofs_mount.md, basic_partition.md, directory_mount.md, systemd_mount.md, udev_mount.md)
- Networking/: network_diagnostics_tools.md, Concepts/(network_latency_optimization.md, rss_rps_rfs.md, tcp_tuning.md), Tools/(ethtool.md, iproute2/tc.md)
- Security/Mechanisms/SELinux.md
- Shell/: quoting.md, shell_intro.md, shell_variables.md
Networking (19 файлов):
- CDN/: cdn_caching_and_invalidation.md, cdn_overview.md
- Concepts/: dpdk_and_sriov.md, dpdk/(dpdk_overview.md, dpdk_technical.md, scenarios.md, sriov.md, sriov_setup.md), firewall_concepts.md, firewall_rules_best_practices.md, network_segmentation_and_microsegmentation.md, sdn/(netflow.md, openflow.md, scenarios.md, sdn_controllers.md, sdn_overview.md), sdn_openflow_netflow.md, vpn_vs_service_mesh.md, zero_trust_overview.md
- OSI_TCP_IP_Model/network_layer.md
- Protocols/: dhcp.md, http_protocols_optimization.md, tls.md
OpenTelemetry (4 файла):
- architecture_signals.md, instrumentation_sdk.md, opentelemetry_overview.md, otlp_protocol.md
Podman (5 файлов):
- alternatives_crio_containerd.md, Concepts/linux_isolation.md, podman_daemonless_architecture.md, podman_rootless.md, podman_vs_docker.md
Prometheus (6 файлов):
- concepts/: metric_types.md, metric_types_overview.md, promql.md
- configuration.md, overview.md, service_discovery_and_relabeling.md
SaltStack (5 файлов):
- Architecture.md, Highstate_and_Execution_Order.md, Orchestration_and_Automation_Methods.md, Security_Approaches.md, User_Creation.md
Security (16 файлов):
- ApplicationSecurity/: ddos_protection_and_waf.md, ddos_waf/(architecture_best_practices.md, ddos_protection_methods.md, ddos_waf_overview.md, scenarios.md, waf.md), xss_and_csp.md
- audit_and_compliance_overview.md
- Secure_Coding/: sdlc_and_secure_sdlc.md, sdlc/(maturity_models.md, practical_scenarios.md, sdlc_overview.md, secure_sdlc.md)
- Supply_Chain_Security/: artifact_signing.md, build_integrity.md, dependency_and_sbom_analysis.md, overview.md
Service_Mesh (5 файлов):
- istio_architecture.md, istio_vs_linkerd.md, proxy_sidecar.md, service_mesh_concepts.md, traffic_management.md
Testing (4 файла):
- testing_cicd_integration.md, testing_coverage_metrics.md, testing_reporting_tools.md, testing_types_unit_integration_e2e.md
Vault (5 файлов):
- concepts.md, guides/transit_key_policy.md, overview.md, security/common_antipatterns.md, zero_trust.md
