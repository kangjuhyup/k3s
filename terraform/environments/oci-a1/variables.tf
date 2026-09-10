variable "oci_region" {
  description = "Explicit target region; null uses OCI_REGION supplied by Doppler. No region is guessed."
  type        = string
  default     = null
}

variable "adoption_reviewed" {
  description = "Set true only after verifying target, backend, ownership and the existing instance configuration. Not authorization to apply."
  type        = bool
  default     = false
  nullable    = false
}

variable "nodes" {
  description = "Existing A1 instances keyed by stable identity, never by list position or IP. Empty until inspected."
  type = map(object({
    existing_instance_ocid  = string
    compartment_id          = string
    availability_domain     = string
    display_name            = string
    role                    = string
    ocpus                   = number
    memory_in_gbs           = number
    subnet_id               = string
    assign_public_ip        = bool
    source_type             = string
    source_id               = string
    boot_volume_size_in_gbs = optional(number)
    boot_volume_vpus_per_gb = optional(number)
    kms_key_id              = optional(string)
    fault_domain            = optional(string)
    hostname_label          = optional(string)
    private_ip              = optional(string)
    nsg_ids                 = optional(set(string))
    skip_source_dest_check  = optional(bool)
    freeform_tags           = optional(map(string))
    defined_tags            = optional(map(string))
  }))
  default  = {}
  nullable = false

  validation {
    condition = alltrue([
      for key, node in var.nodes :
      try(can(regex("^[a-z][a-z0-9_-]*$", key)) &&
        contains(["server", "agent"], node.role) &&
        try(node.ocpus > 0 && node.memory_in_gbs > 0, false) &&
        try(length(trimspace(node.availability_domain)) > 0, false) &&
        try(length(trimspace(node.display_name)) > 0, false) &&
      node.assign_public_ip != null, false)
    ])
    error_message = "Use stable lowercase node keys, server/agent roles, positive sizing and explicit existing placement/name/public-IP settings."
  }

  validation {
    condition = alltrue([
      for node in values(var.nodes) :
      try(can(regex("^ocid1\\.instance\\.", node.existing_instance_ocid)) &&
        can(regex("^ocid1\\.(compartment|tenancy)\\.", node.compartment_id)) &&
        can(regex("^ocid1\\.subnet\\.", node.subnet_id)) &&
        contains(["image", "bootVolume"], node.source_type) &&
      can(regex(node.source_type == "bootVolume" ? "^ocid1\\.bootvolume\\." : "^ocid1\\.image\\.", node.source_id)), false)
    ])
    error_message = "Every node requires existing instance/subnet OCIDs, a compartment or root tenancy OCID, and an image or bootVolume source of the matching OCID type. Placeholders are not runnable inputs."
  }

  validation {
    condition     = try(length(distinct([for node in values(var.nodes) : node.existing_instance_ocid])) == length(var.nodes), false)
    error_message = "An existing instance must have exactly one Terraform address; duplicate instance OCIDs are forbidden."
  }
}

variable "metadata_by_node" {
  description = "Existing opaque metadata only when needed to match import, injected as TF_VAR_metadata_by_node from Doppler. Never put real values in Git."
  type        = map(map(string))
  sensitive   = true
  default     = {}
  nullable    = false

  validation {
    condition     = alltrue([for key in keys(var.metadata_by_node) : contains(keys(var.nodes), key)])
    error_message = "Metadata entries must reference managed node keys."
  }
}
