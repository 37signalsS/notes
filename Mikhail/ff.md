# [Bare Metal Kubernetes: Deploying Without Virtualization | DigitalOcean](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev)
### [Introduction](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#introduction)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#introduction) ###

A bare metal Kubernetes deployment is the process of setting up a Kubernetes cluster directly on [bare metal](https://www.digitalocean.com/community/conceptual-articles/what-is-bare-metal-hypervisor) servers. This approach provides unparalleled performance and control, eliminating the overhead associated with virtualization. It is ideal for workloads that demand high efficiency, such as [AI/ML applications](https://www.digitalocean.com/products/ai-ml) and high-performance computing tasks. In this tutorial, you will learn to set up a Kubernetes cluster on bare metal infrastructure, covering prerequisites, installation steps, networking configurations, monitoring, and best practices.

[Bare-Metal Kubernetes vs VM-based Kubernetes](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#bare-metal-kubernetes-vs-vm-based-kubernetes)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#bare-metal-kubernetes-vs-vm-based-kubernetes)
----------

|      Feature       |Bare-Metal Kubernetes|VM-based Kubernetes|
|--------------------|---------------------|-------------------|
|    Performance     |        High         |     Moderate      |
|      Overhead      |         Low         |       High        |
|    Flexibility     |        High         |     Moderate      |
|Resource Utilization|      Efficient      |    Inefficient    |
|    Scalability     |        High         |     Moderate      |
|        Cost        |         Low         |       High        |

Bare-Metal [Kubernetes](https://www.digitalocean.com/products/kubernetes) is a deployment approach that sets up a Kubernetes cluster directly on [bare metal servers](https://www.digitalocean.com/products/bare-metal-gpu). This approach provides high performance, low overhead, and high flexibility. It efficiently utilizes resources and is highly scalable, all at a low cost.

On the other hand, VM-based Kubernetes deploys a Kubernetes cluster on virtual machines. This approach provides moderate performance, high overhead, and moderate flexibility. It utilizes resources inefficiently and is moderately scalable, all at a high cost.

![Difference between Bare-metal K8s and VM-Based K8s](https://doimages.nyc3.cdn.digitaloceanspaces.com/006Community/Bare-metal-k8s-tutorial/bare-metal-k8s.png)

[Advantages of Bare Metal Kubernetes Deployment](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#advantages-of-bare-metal-kubernetes-deployment)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#advantages-of-bare-metal-kubernetes-deployment)
----------

Before diving into the deployment process, it’s essential to understand the advantages of running Kubernetes on bare metal:

1. **Enhanced Performance:** Direct access to hardware resources ensures minimal latency and maximized throughput.

2. **Resource Efficiency**: Eliminating the hypervisor layer reduces overhead, allowing applications to utilize the full potential of the hardware.

3. **Cost Savings**: By optimizing resource utilization, organizations can achieve better performance-per-dollar compared to virtualized environments.

4. **Flexibility**: Full control over hardware configurations enables customization tailored to specific workload requirements.

[Prerequisites](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#prerequisites)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#prerequisites)
----------

Ensure the following prerequisites are met before proceeding:

**Hardware Requirements:**

1. **Master Node**: At least 4 CPUs, 16GB RAM, and 100GB SSD storage.

2. **Worker Nodes**: At least 2 CPUs, 8GB RAM, and 100GB SSD storage per node.

**Operating System**: Ubuntu 24.04 LTS(or above) or CentOS 9 Stream installed on all nodes.

**Network Configuration:**

1. Static IP addresses are assigned to each node.

2. Proper DNS settings configured.

**Access:**

1. [SSH access](https://www.digitalocean.com/community/tutorial-collections/how-to-set-up-ssh-keys) with root or sudo privileges on all nodes.

[Step 1 - Prepare the Nodes](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-1-prepare-the-nodes)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-1-prepare-the-nodes)
----------

You need to follow these steps on all master and worker nodes.

### [1. Update System Packages](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#1-update-system-packages)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#1-update-system-packages) ###

Run the following command on all nodes to ensure they are up-to-date:

```
sudoapt update &&sudoapt upgrade -y
```

### [2. Set Hostnames and Hosts File](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#2-set-hostnames-and-hosts-file)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#2-set-hostnames-and-hosts-file) ###

Assign a unique hostname to each node. On each node, run:

```
sudo hostnamectl set-hostname <node-name>
```

Edit `/etc/hosts` on all nodes to include the IP addresses and hostnames of all other nodes:

```
192.168.1.100 master-node
192.168.1.101 worker-node1
192.168.1.102 worker-node2

```

Please Note that, if the nodes are on the same private network (e.g., in the same VPC or subnet), use their private IP addresses instead for better security and performance. You can use the public IPs instead of private IPs if nodes are on different networks.

### [3. Disable Swap](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#3-disable-swap)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#3-disable-swap) ###

[Swap](https://phoenixnap.com/kb/swap-memory#:~:text=Swap%20memory%2C%20also%20known%20as,preventing%20system%20slowdowns%20or%20crashes.) is a space on a disk that is used when the amount of physical RAM memory is full. When a Linux system runs out of RAM, inactive pages are moved from the RAM to the swap space. Disabling swap is recommended for Kubernetes as it can cause issues with the container runtime. To disable the swap, run the following commands:

```
sudo swapoff -asudosed-i'/ swap / s/^/#/' /etc/fstab

```

### [4. Load Necessary Kernel Modules](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#4-load-necessary-kernel-modules)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#4-load-necessary-kernel-modules) ###

Run the following on all nodes to enable the required networking modules:

```
sudo modprobe br_netfilter
sudotee /etc/modules-load.d/k8s.conf <<EOF
br_netfilter
EOFsudotee /etc/sysctl.d/k8s.conf <<EOF
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
EOFsudosysctl--system
```

[Step 2 - Install Container Runtime](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-2-install-container-runtime)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-2-install-container-runtime)
----------

A [container runtime](https://kubernetes.io/docs/setup/production-environment/container-runtimes/) is a software that is responsible for running containers. It is a crucial component of any containerized environment. Some examples of famous container runtimes are [Docker](https://kubernetes.io/docs/setup/production-environment/container-runtimes/#docker), [containerd](https://kubernetes.io/docs/setup/production-environment/container-runtimes/#containerd), and [CRI-O](https://kubernetes.io/docs/setup/production-environment/container-runtimes/#cri-o). On all master and worker nodes, you will need to install the container runtime.

Follow the below steps on all the master and worker nodes:

In this tutorial, you will use the `containerd` container runtime.

```
sudoaptinstall-y containerd

```

```
sudomkdir-p /etc/containerd
sudo containerd config default |sudotee /etc/containerd/config.toml
sudo systemctl restart containerd
sudo systemctl enable containerd

```

[Step 3 - Install Kubernetes Components](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-3-install-kubernetes-components)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-3-install-kubernetes-components)
----------

On all the master and worker nodes, follow these steps to install the Kubernetes components:

```
sudocurl-fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key |sudo gpg --dearmor-o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

echo'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /'|sudotee /etc/apt/sources.list.d/kubernetes.list

sudoapt-get update

sudoapt-getinstall-y kubelet kubeadm kubectl

sudo apt-mark hold kubelet kubeadm kubectl

```

Once the installation is complete, verify the installation by checking the versions:

```
kubectl version --client
kubeadm version

```

Check the status of the kubelet service:

```
sudo systemctl status kubelet

```

If the service is not active, start it:

```
sudo systemctl start kubelet
sudo systemctl enable kubelet

```

That’s it! You have now installed the Kubernetes components on your bare metal Ubuntu machines.

[Step 4 - Initialize the Kubernetes Cluster (Run this only on the master node)](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-4-initialize-the-kubernetes-cluster-run-this-only-on-the-master-node)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-4-initialize-the-kubernetes-cluster-run-this-only-on-the-master-node)
----------

On the master node, initialize the Kubernetes cluster using the following command:

```
sudo kubeadm init --pod-network-cidr=192.168.0.0/16

```

**Note:** If you notice the following error while initializing the k8s cluster using the above command on the master node:

```
I0227 09:37:20.755567    4052 version.go:256] remote version is much newer: v1.32.2; falling back to: stable-1.29
[init] Using Kubernetes version: v1.29.14
[preflight] Running pre-flight checks
error execution phase preflight: [preflight] Some fatal errors occurred:
        [ERROR FileContent--proc-sys-net-ipv4-ip_forward]: /proc/sys/net/ipv4/ip_forward contents are not set to 1[preflight] If you know what you are doing, you can make a check non-fatal with `--ignore-preflight-errors=...`
To see the stack trace of this error execute with --v=5 or higher

```

The error message indicates that the `ip_forward` setting in your system is not enabled. This setting is necessary for Kubernetes to allow network traffic to be forwarded between pods and nodes. To fix this error, you need to enable IP forwarding.

**Enable IP Forwarding Temporarily:**

```
sudosysctl-wnet.ipv4.ip_forward=1
```

This command will initialize the Kubernetes control plane and generate a `kubeconfig` file. It will also print the next steps and the command to join the worker nodes to the cluster.

After the initialization is complete, you will see a message that looks like this:

```
Your Kubernetes control-plane has initialized successfully!

To start using your cluster, you need to run the following as a regular user:

  mkdir-p$HOME/.kube
  sudocp-i /etc/kubernetes/admin.conf $HOME/.kube/config
  sudochown$(id-u):$(id-g)$HOME/.kube/config

You should now deploy a pod network to the cluster.
Run "kubectl apply -f [podnetwork].yaml" with one of the options listed at:
  https://kubernetes.io/docs/concepts/cluster-administration/networking/

<^>Then you can join any number of worker nodes by running the following on each as root:
kubeadm join192.168.0.100:6443 --token 9vz3zv.3x3z3z3z3z3z3z3z \<^>
```

**Note:** In the above output of a successful Kubernetes control plane deployment, please make a note of `kubeadm join` command and the `--token` and `--discovery-token-ca-cert-hash sha256` values as you will need it in the upcoming steps when joining worker nodes to the Kubernetes cluster.

To start using your cluster, you need to run the following as a regular user:

```
mkdir-p$HOME/.kube
sudocp-i /etc/kubernetes/admin.conf $HOME/.kube/config
sudochown$(id-u):$(id-g)$HOME/.kube/config

```

Alternatively, if you are the `root` user, you can run:

```
exportKUBECONFIG=/etc/kubernetes/admin.conf

```

You should now deploy a pod network to the cluster.

[Step 5 - Open Kubernetes Ports and Deploy a Pod Network](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-5-open-kubernetes-ports-and-deploy-a-pod-network)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-5-open-kubernetes-ports-and-deploy-a-pod-network)
----------

To deploy a pod network to your Kubernetes cluster, you can use [network plugins](https://kubernetes.io/docs/concepts/cluster-administration/addons/) like Calico, Flannel, or Weave. Here, you will use Flannel.

This command should be run on the **master node.**

### [Open Kubernetes Ports](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#open-kubernetes-ports)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#open-kubernetes-ports) ###

Before installing the Pod Network, you need to ensure that the required Kubernetes ports are open. These ports are used by various Kubernetes services:

To open these ports, you can use the following commands:

```
sudo ufw allow 6443/tcp
sudo ufw allow 10250/tcp
sudo ufw allow 2379:2380/tcp

```

### [Deploy Pod Network](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#deploy-pod-network)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#deploy-pod-network) ###

Now, let’s install the Pod network using the [Flannel](https://github.com/flannel-io/flannel#deploying-flannel-manually) network plugin.

```
kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml

```

A successful pod network deployment will give the below output:

```
namespace/kube-flannel created
clusterrole.rbac.authorization.k8s.io/flannel created
clusterrolebinding.rbac.authorization.k8s.io/flannel created
serviceaccount/flannel created
configmap/kube-flannel-cfg created
daemonset.apps/kube-flannel-ds created

```

This command will deploy the [Flannel](https://github.com/flannel-io/flannel) pod network to your cluster. You can verify the deployment by running:

```
kubectl get pods --all-namespaces

```

You should see the **Flannel** pods running in the `kube-system` namespace.

```
kube-flannel   kube-flannel-ds-bs6df                       1/1     Running             1(82s ago)      94s
kube-system    coredns-76f75df574-md5b2                    0/1     ContainerCreating   0                105s
kube-system    coredns-76f75df574-wdpsd                    0/1     ContainerCreating   0                105s
kube-system    etcd-master-node-anish                      1/1     Running             16(2m48s ago)   2m49s
kube-system    kube-apiserver-master-node-anish            1/1     Running             21(2m18s ago)   2m15s
kube-system    kube-controller-manager-master-node-anish   1/1     Running             1(2m48s ago)    80s
kube-system    kube-proxy-vsr5m                            1/1     Running             3(83s ago)      105s
kube-system    kube-scheduler-master-node-anish            1/1     Running             21(2m48s ago)   2m50s

```

If you want to get your Kubernetees cluster details, you can use the following command:

```
kubectl cluster-info

```

This should give you the following output:

```
Kubernetes control plane is running at https://64.227.157.182:6443
CoreDNS is running at https://64.227.157.182:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

To further debug and diagnose cluster problems, use 'kubectl cluster-info dump'.
```

[Step 6 - Join Worker Nodes](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-6-join-worker-nodes)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-6-join-worker-nodes)
----------

To join the worker nodes to the Kubernetes cluster, you will need to run the following `kubectl join` command on each worker node.

```
sudo kubeadm join<MASTER_NODE_IP>:6443 --token<TOKEN> --discovery-token-ca-cert-hash sha256:<HASH>
```

Replace `<MASTER_NODE_IP>` with the IP address of your master node IP, `<TOKEN>` with the token generated during the master node setup, and `<HASH>` with the hash generated during the master node setup.

Once you have run this command on all worker nodes, you can verify that they have joined the cluster by running:

```
kubectl get nodes

```

You should see all worker nodes listed and in the `Ready` state.

```
master-node-anish   Ready    control-plane   13m     v1.29.14
worker-node-anish   Ready    <none>          7m27s   v1.29.14

```

[Step 7 - Deploy a Sample Application](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-7-deploy-a-sample-application)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-7-deploy-a-sample-application)
----------

In this step, you will deploy a sample application, specifically an `nginx` server. This can be done using the following command:

```
kubectl create deployment nginx --image=nginx

```

This command will create a deployment named `nginx` and use the `nginx` image.

Next, we will expose the deployment `nginx` to the outside world on port `80`. The `--type=NodePort` flag specifies that the service should be exposed on a [NodePort](https://kubernetes.io/docs/concepts/services-networking/service/#type-nodeport).

```
kubectl expose deployment nginx --port=80--type=NodePort

```

After running these commands, you can access the `nginx` server by using the IP address of any of your worker nodes and the NodePort that was assigned to the `nginx` service. You can find the NodePort by running the following command:

```
kubectl get svc

```

You should see the newly created `nginx` service listed, along with its NodePort.

```
NAME         TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)        AGE
kubernetes   ClusterIP   10.96.0.1      <none>443/TCP        18m
nginx        NodePort    10.111.19.83   <none>80:32224/TCP   8s

```

### [Access the Application](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#access-the-application)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#access-the-application) ###

To access the `nginx` service, you can use the IP address of any of your **worker nodes** and the `NodePort` that was assigned to the `nginx` service.

You can find the `NodePort` by running the following command:

```
kubectl get svc

```

You should see the newly created `nginx` service listed, along with its NodePort.

```
NAME         TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)        AGE
kubernetes   ClusterIP   10.96.0.1      <none>443/TCP        18m
nginx        NodePort    10.111.19.83   <none>80:32224/TCP   8s

```

In this example, the NodePort for the `nginx` service is `32224`. You can access the `nginx` server by using the IP address of any of your worker nodes and the NodePort. For example, if the IP address of your worker node is `10.111.19.83`, you can access the `nginx` server at `http://10.111.19.83:32224`.

[Step 8 - Monitoring Kubernetes on Bare Metal](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-8-monitoring-kubernetes-on-bare-metal)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-8-monitoring-kubernetes-on-bare-metal)
----------

Kubernetes provides a rich set of monitoring tools and integrations. Some of the popular ones are:

* **Prometheus**: A monitoring system and time series database.
* **Grafana**: A visualization tool that works with Prometheus to create and display dashboards.
* **Kube-state-metrics**: A service that listens to the Kubernetes API server and generates metrics about the state of the objects.

To set up monitoring for your Kubernetes cluster, you can follow this tutorial on [How to Set Up DigitalOcean Kubernetes Cluster Monitoring with Helm and Prometheus Operator](https://www.digitalocean.com/community/tutorials/how-to-set-up-digitalocean-kubernetes-cluster-monitoring-with-helm-and-prometheus-operator).

[FAQs](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#faqs)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#faqs)
----------

### [1. Can Kubernetes be installed on bare metal?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#1-can-kubernetes-be-installed-on-bare-metal)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#1-can-kubernetes-be-installed-on-bare-metal) ###

Yes, [Kubernetes](https://www.digitalocean.com/products/kubernetes) can be installed on physical servers without virtualization, providing direct access to hardware resources.

### [2. What is the simplest way to deploy Kubernetes?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#2-what-is-the-simplest-way-to-deploy-kubernetes)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#2-what-is-the-simplest-way-to-deploy-kubernetes) ###

The simplest way to deploy Kubernetes on bare metal is by using [`kubeadm`](https://kubernetes.io/docs/reference/setup-tools/kubeadm/), which automates the [cluster setup process](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/).

### [3. Is it possible to run Kubernetes without Docker?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#3-is-it-possible-to-run-kubernetes-without-docker)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#3-is-it-possible-to-run-kubernetes-without-docker) ###

Yes, [Kubernetes](https://www.digitalocean.com/products/kubernetes) supports other container runtimes like `containerd` and `CRI-O`. Docker is no longer required since Kubernetes deprecated Docker support in v1.20.

### [4. Is Docker better on bare metal or VM?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#4-is-docker-better-on-bare-metal-or-vm)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#4-is-docker-better-on-bare-metal-or-vm) ###

Docker performs better on bare metal because it eliminates the overhead of a hypervisor, allowing direct access to system resources. However, VMs provide better isolation and security.

### [5. Can you use Kubernetes without helm?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#5-can-you-use-kubernetes-without-helm)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#5-can-you-use-kubernetes-without-helm) ###

Yes, you can manually deploy applications using Kubernetes manifests (`kubectl apply -f`). However, Helm simplifies package management and application deployment.

### [6. What is bare metal Kubernetes, and why use it?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#6-what-is-bare-metal-kubernetes-and-why-use-it)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#6-what-is-bare-metal-kubernetes-and-why-use-it) ###

[Bare metal](https://www.digitalocean.com/products/bare-metal-gpu) Kubernetes refers to running Kubernetes directly on physical machines instead of virtualized environments. It is used for enhanced performance, reduced latency, and better resource efficiency, making it ideal for AI/ML and high-performance workloads.

### [7. How does Kubernetes deployment on bare metal differ from cloud setups?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#7-how-does-kubernetes-deployment-on-bare-metal-differ-from-cloud-setups)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#7-how-does-kubernetes-deployment-on-bare-metal-differ-from-cloud-setups) ###

In cloud setups, Kubernetes nodes run on virtual machines managed by a cloud provider. Bare metal deployments require manual setup and configuration, but offer greater flexibility, cost efficiency, and performance.

### [8. What tools are required to deploy Kubernetes on bare metal?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#8-what-tools-are-required-to-deploy-kubernetes-on-bare-metal)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#8-what-tools-are-required-to-deploy-kubernetes-on-bare-metal) ###

You need:

### [9. Can bare metal Kubernetes clusters scale like cloud environments?](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#9-can-bare-metal-kubernetes-clusters-scale-like-cloud-environments)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#9-can-bare-metal-kubernetes-clusters-scale-like-cloud-environments) ###

Yes, but scaling requires manual provisioning of additional nodes and network configurations, unlike cloud environments where resources are automatically allocated.

For additional guidance, check out [DigitalOcean DOKS Managed Kubernetes Networking](https://www.digitalocean.com/blog/digitalocean-doks-managed-kubernetes-networking).

[Conclusion](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#conclusion)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#conclusion)
----------

In this comprehensive tutorial, you learned how to deploy Kubernetes on bare metal infrastructure. We covered the key aspects of setting up a Kubernetes cluster on physical machines, including the use of `kubeadm` for automation, the importance of container runtimes like `containerd` and `CRI-O`, and the role of networking plugins such as Calico and Flannel.

By following this tutorial, you should now have a solid understanding of how to deploy and manage a Kubernetes cluster on bare metal, taking advantage of the performance, control, and efficiency it offers.














# [Kubernetes на голом железе: развертывание без виртуализации | DigitalOcean](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev)
### [Введение](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#introduction)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#introduction) ###

Развёртывание Kubernetes на «голом железе» — это процесс настройки кластера Kubernetes непосредственно на [серверах «голого железа»](https://www.digitalocean.com/community/conceptual-articles/what-is-bare-metal-hypervisor). Такой подход обеспечивает беспрецедентную производительность и контроль, устраняя издержки, связанные с виртуализацией. Он идеально подходит для рабочих нагрузок, требующих высокой эффективности, таких как [приложения искусственного интеллекта и машинного обучения](https://www.digitalocean.com/products/ai-ml) и высокопроизводительные вычисления. В этом руководстве вы узнаете, как настроить кластер Kubernetes на инфраструктуре без операционной системы, включая предварительные требования, этапы установки, сетевые конфигурации, мониторинг и передовые методы.

[Kubernetes на голом железе в сравнении с Kubernetes на виртуальных машинах](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#bare-metal-kubernetes-vs-vm-based-kubernetes)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#bare-metal-kubernetes-vs-vm-based-kubernetes)
----------

|      Характеристика       |Kubernetes на голом железе|Kubernetes на виртуальных машинах|
|--------------------|---------------------|-------------------|
|    Производительность     |        Высокая         |     Умеренная      |
|      Накладные расходы      |         Низкие         |       Высокие        |
|    Гибкость     |        Высокая         |     Умеренная      |
|Использование ресурсов|      Эффективное      |    Неэффективное    |
|    Масштабируемость     |        Высокая         |     Умеренная      |
|        Стоимость        |         Низкая         |       Высокая        |

Bare-Metal [Kubernetes](https://www.digitalocean.com/products/kubernetes) — это подход к развёртыванию, при котором кластер Kubernetes настраивается непосредственно на [серверах Bare-Metal](https://www.digitalocean.com/products/bare-metal-gpu). Этот подход обеспечивает высокую производительность, низкие накладные расходы и высокую гибкость. Он эффективно использует ресурсы и обладает высокой масштабируемостью при низкой стоимости.

С другой стороны, Kubernetes на основе виртуальных машин развертывает кластер Kubernetes на виртуальных машинах. Этот подход обеспечивает умеренную производительность, высокие накладные расходы и умеренную гибкость. Он неэффективно использует ресурсы и обладает умеренной масштабируемостью, но при этом требует больших затрат.

![Разница между K8s на голом железе и K8s на основе виртуальных машин](https://doimages.nyc3.cdn.digitaloceanspaces.com/006Community/Bare-metal-k8s-tutorial/bare-metal-k8s.png)

[Преимущества развертывания Kubernetes на голом железе](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#advantages-of-bare-metal-kubernetes-deployment)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#advantages-of-bare-metal-kubernetes-deployment)
----------

Прежде чем приступить к развертыванию, важно понять преимущества запуска Kubernetes на голом железе:

1. ** Повышенная производительность: ** Прямой доступ к аппаратным ресурсам обеспечивает минимальную задержку и максимальную пропускную способность.

2. ** Эффективность использования ресурсов**: Устранение уровня гипервизора снижает накладные расходы, позволяя приложениям использовать весь потенциал аппаратного обеспечения.

3. ** Экономия средств**: Оптимизируя использование ресурсов, организации могут добиться более высокой производительности в расчете на доллар по сравнению с виртуализированными средами.

4. **Гибкость**: Полный контроль над конфигурациями оборудования позволяет адаптировать его к конкретным требованиям рабочей нагрузки.

[Предварительные требования](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#prerequisites)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#prerequisites)
----------

Перед продолжением убедитесь, что выполнены следующие предварительные требования:

**Требования к оборудованию:**

1. **Главный узел**: не менее 4 процессоров, 16 ГБ оперативной памяти и 100 ГБ SSD-накопителя.

2. **Рабочие узлы**: не менее 2 процессоров, 8 ГБ оперативной памяти и 100 ГБ SSD-накопителя на каждый узел.

**Операционная система**: Ubuntu 24.04 LTS (или выше) или CentOS 9 Stream, установленная на всех узлах.

**Сетевая конфигурация:**

1. Каждому узлу назначены статические IP-адреса.

2. Настроены правильные параметры DNS.

**Доступ:**

1. [Доступ по SSH](https://www.digitalocean.com/community/tutorial-collections/how-to-set-up-ssh-keys) с правами root или sudo на всех узлах.

[Шаг 1. Подготовка узлов](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-1-prepare-the-nodes)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-1-prepare-the-nodes)
----------

Вам нужно выполнить эти действия на всех главных и рабочих узлах.

### [1. Обновление системных пакетов](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#1-update-system-packages)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#1-update-system-packages) ###

Выполните следующую команду на всех узлах, чтобы убедиться, что они обновлены:

```
sudo apt update && sudo apt upgrade -y
```

### [2. Настройка имен хостов и файла hosts](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#2-set-hostnames-and-hosts-file)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#2-set-hostnames-and-hosts-file) ###

Присвойте каждому узлу уникальное имя хоста. На каждом узле выполните:

```
sudo hostnamectl set-hostname <имя_узла>
```

Отредактируйте `/etc/hosts` на всех узлах, чтобы включить IP-адреса и имена хостов всех остальных узлов:

```
192.168.1.100 главный_узел
192.168.1.101 рабочий_узел1
192.168.1.102 рабочий_узел2

```

Обратите внимание, что если узлы находятся в одной частной сети (например, в одном VPC или подсети), для повышения безопасности и производительности используйте их частные IP-адреса. Если узлы находятся в разных сетях, вместо частных IP-адресов можно использовать общедоступные IP-адреса.

### [3. Отключите своп](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#3-disable-swap)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#3-disable-swap) ###

[Виртуальная память](https://phoenixnap.com/kb/swap-memory#:~:text=Виртуальная%20память%2C%20также%20известная%20как,предотвращая%20замедление%20работы%20системы%20или%20сбои.) — это пространство на диске, которое используется, когда объём физической оперативной памяти заполнен. Когда в системе Linux заканчивается оперативная память, неактивные страницы перемещаются из оперативной памяти в пространство виртуальной памяти. Для Kubernetes рекомендуется отключить своп, так как он может вызывать проблемы с выполнением контейнеров. Чтобы отключить своп, выполните следующие команды:

```
sudo swapoff -asudosed-i'/ swap / s/^/#/' /etc/fstab

```

### [4. Загрузите необходимые модули ядра](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#4-load-necessary-kernel-modules)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#4-load-necessary-kernel-modules) ###

Выполните следующие действия на всех узлах, чтобы включить необходимые сетевые модули:

```
sudo modprobe br_netfilter
sudotee /etc/modules-load.d/k8s.conf <<EOF
br_netfilter
EOFsudotee /etc/sysctl.d/k8s.conf <<EOF
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
EOFsudosysctl--system
```

[Шаг 2. Установка среды выполнения контейнеров](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-2-install-container-runtime)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-2-install-container-runtime)
----------

[Среда выполнения контейнеров](https://kubernetes.io/docs/setup/production-environment/container-runtimes/) — это программное обеспечение, отвечающее за запуск контейнеров. Это важнейший компонент любой контейнерной среды. Вот несколько примеров известных сред выполнения контейнеров: [Docker](https://kubernetes.io/docs/setup/production-environment/container-runtimes/#docker), [containerd](https://kubernetes.io/docs/setup/production-environment/container-runtimes/#containerd) и [CRI-O](https://kubernetes.io/docs/setup/production-environment/container-runtimes/#cri-o). На всех главных и рабочих узлах необходимо установить среду выполнения контейнеров.

Выполните следующие действия на всех главных и рабочих узлах:

В этом руководстве вы будете использовать среду выполнения контейнеров `containerd`. 

```
sudo apt-get install -y containerd

```

```
sudo mkdir -p /etc/containerd
sudo containerd config default | sudo tee /etc/containerd/config.toml
sudo systemctl restart containerd
sudo systemctl enable containerd

```

[Шаг 3. Установка компонентов Kubernetes](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-3-install-kubernetes-components)[](https://www.digitalocean.com/community/tutorials/bare-metal-kubernetes?ref=dailydev#step-3-install-kubernetes-components)
----------

На всех главных и рабочих узлах выполните следующие действия для установки компонентов Kubernetes:

```
sudo curl-fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | sudo gpg --dearmor-o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

echo'deb [подписанный-ключом=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /'|sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update

sudo apt-get install -y kubelet kubeadm kubectl

sudo apt-mark hold kubelet kubeadm kubectl

```

После завершения установки проверьте ее, проверив версии:

```
kubectl version --client
kubeadm version

```

Проверьте состояние службы kubelet:

```
sudo systemctl status kubelet

```

Если служба не активна, запустите ее:

```
sudo systemctl start kubelet
sudo systemctl enable kubelet

```

Вот и всё! Теперь вы установили компоненты Kubernetes на свои компьютеры Ubuntu без операционной системы.