output "nodes" {
  description = "Selected non-secret inventory inputs. No SSH user, reachable address or Kubernetes role is inferred from the guest OS."
  value = {
    for key, instance in oci_core_instance.nodes : key => {
      instance_ocid = instance.id
      role          = var.nodes[key].role
      private_ip    = instance.private_ip
      public_ip     = instance.public_ip
    }
  }
}
