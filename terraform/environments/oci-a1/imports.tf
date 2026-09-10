# Import declarations must remain paired with the resource map. An OCID
# is mandatory: adding a node here is not a request to launch a new VM.
import {
  for_each = var.nodes
  to       = oci_core_instance.nodes[each.key]
  id       = each.value.existing_instance_ocid
}
