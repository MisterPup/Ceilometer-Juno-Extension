==========================================
Ceilometer-Juno-Extension
==========================================

| This work is an extension to the monitoring project of OpenStack, Ceilometer.
| It has been realized in the context of the Master's Thesis:
| "*A unified framework for resources monitoring and virtual machines migration in OpenStack*"
| https://github.com/MisterPup/OpenStack-Neat-Ceilometer
|
The following changes have been added to Ceilometer:

* A Pipeline was previously defined as the coupling between a source and a sink.
  We have redifined it as the association between **one or more** sources and a sink.
  In this way, by mean of the multi meter arithmetic transformer we can combine
  samples of meters from heterogeneous sources (e.g., CPU and RAM).
  
* A new type of transformer has been added: the **Selective Transformer**. A selective transformer
  applies transformation to a subset of samples in a pipeline (not all as previously defined).
  This is useful when we want to combine *cpu_util* and *memory.usage*, because samples of the
  first meter are produced by mean of the *rate of change transformation*, and not collected directly
  by a pollster (in libvirt).
  
* We have created two new meters: *Host Cpu Usage* (*host.cpu.time*) and *Host Memory Usage* (*host.memory.usage*).
  The first was already present in form of notification, while the second is totally new.
  
* For the new meters, two new pollsters have been created. Each pollster collect samples by means of the
  functions of the hypervisor inspector. The functions are inspired by the code of the commands 
  *virsh nodecpustats* and *virsh nodememstats*.

* We have create a new discovery, *HostResourceIdDiscovery*, which returns the id of the host on which the
  compute agent is running.

* Tests have been made with libvirt and KVM.

==========================================
Selective Transformer
==========================================

Here we propose an example of pipeline that produces in output a combination of *host.cpu.time* and *host.memory.usage*

|    - name: host_cpu_util_memory_usage_sink    
|      transformers:
|          - name: "rate_of_change"
|            parameters:
|                apply_to:
|                    - "host.cpu.time"
|                target:
|                    name: "host.cpu.util"
|                    unit: "%" 
|                    type: "gauge"
|                    scale: "100.0 / (10**9 * (resource_metadata.cpu_number or 1))"  
|          - name: "arithmetic"
|            parameters:
|                apply_to:
|                    - "*"
|                target:
|                    name: "host.cpu.util.memory.usage"
|                    unit: ""
|                    type: "cumulative"
|                    expr: "0.5*$(host.cpu.util)/100 + 0.5*$(host.memory.usage)/100"
|      publishers:
|          - rpc://
