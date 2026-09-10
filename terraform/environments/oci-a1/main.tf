# Adoption baseline only. No network, security rules, volumes or software
# are created separately. Inspect all imported settings before any apply.
resource "oci_core_instance" "nodes" {
  for_each = var.nodes

  compartment_id      = each.value.compartment_id
  availability_domain = each.value.availability_domain
  display_name        = each.value.display_name
  fault_domain        = each.value.fault_domain
  shape               = "VM.Standard.A1.Flex"
  freeform_tags       = each.value.freeform_tags
  defined_tags        = each.value.defined_tags
  metadata            = lookup(var.metadata_by_node, each.key, null)

  shape_config {
    ocpus         = each.value.ocpus
    memory_in_gbs = each.value.memory_in_gbs
  }

  create_vnic_details {
    subnet_id              = each.value.subnet_id
    assign_public_ip       = each.value.assign_public_ip
    hostname_label         = each.value.hostname_label
    private_ip             = each.value.private_ip
    nsg_ids                = each.value.nsg_ids
    skip_source_dest_check = each.value.skip_source_dest_check
  }

  source_details {
    source_type             = each.value.source_type
    source_id               = each.value.source_id
    boot_volume_size_in_gbs = each.value.boot_volume_size_in_gbs
    boot_volume_vpus_per_gb = each.value.boot_volume_vpus_per_gb
    kms_key_id              = each.value.kms_key_id
  }

  preserve_boot_volume = true

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = var.adoption_reviewed
      error_message = "Adoption is blocked until OCI target, backend, ownership and current configuration have been reviewed. SSH is not required for that review."
    }
  }
}
