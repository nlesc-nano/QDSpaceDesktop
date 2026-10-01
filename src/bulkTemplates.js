// Bulk CIF templates served from qd-frontend/public/<family>/bulk_cifs/.
// Shared by the Builder (template picker) and the Library (hand-off to the Builder).
export const bulkTemplates = {
  "ABX3": [
    { name: "CsPbCl3", phase: "cubic", a: 5.680, path: "/ABX3/bulk_cifs/CsPbCl3_cubic.cif" },
    { name: "CsPbBr3", phase: "cubic", a: 5.949, path: "/ABX3/bulk_cifs/CsPbBr3_cubic.cif" },
    { name: "CsPbI3", phase: "cubic", a: 6.275, path: "/ABX3/bulk_cifs/CsPbI3_cubic.cif" }
  ],
  "II-VI": [
    { name: "CdS", phase: "zinc-blende", a: 5.886, path: "/II-VI/bulk_cifs/CdS_zb.cif" },
    { name: "CdSe", phase: "zinc-blende", a: 6.141, path: "/II-VI/bulk_cifs/CdSe_zb.cif" },
    { name: "CdTe", phase: "zinc-blende", a: 6.564, path: "/II-VI/bulk_cifs/CdTe_zb.cif" },
    { name: "CdSe", phase: "wurtzite", a: 4.346, c: 7.090, path: "/II-VI/bulk_cifs/CdSe_wz.cif" },
    { name: "ZnS", phase: "zinc-blende", a: 5.387, path: "/II-VI/bulk_cifs/ZnS_zb.cif" },
    { name: "ZnSe", phase: "zinc-blende", a: 5.665, path: "/II-VI/bulk_cifs/ZnSe_zb.cif" },
    { name: "ZnTe", phase: "zinc-blende", a: 6.111, path: "/II-VI/bulk_cifs/ZnTe_zb.cif" },
    { name: "HgS", phase: "zinc-blende", a: 5.939, path: "/II-VI/bulk_cifs/HgS_zb.cif" },
    { name: "HgSe", phase: "zinc-blende", a: 6.193, path: "/II-VI/bulk_cifs/HgSe_zb.cif" },
    { name: "HgTe", phase: "zinc-blende", a: 6.580, path: "/II-VI/bulk_cifs/HgTe_zb.cif" }
  ],
  "III-V": [
    { name: "AlP", phase: "zinc-blende", a: 5.470, path: "/III-V/bulk_cifs/AlP_zb.cif" },
    { name: "AlAs", phase: "zinc-blende", a: 5.680, path: "/III-V/bulk_cifs/AlAs_zb.cif" },
    { name: "AlSb", phase: "zinc-blende", a: 6.190, path: "/III-V/bulk_cifs/AlSb_zb.cif" },
    { name: "GaAs", phase: "zinc-blende", a: 5.750, path: "/III-V/bulk_cifs/GaAs_zb.cif" },
    { name: "GaP", phase: "zinc-blende", a: 5.452, path: "/III-V/bulk_cifs/GaP_zb.cif" },
    { name: "GaSb", phase: "zinc-blende", a: 6.137, path: "/III-V/bulk_cifs/GaSb_zb.cif" },
    { name: "InAs", phase: "zinc-blende", a: 6.107, path: "/III-V/bulk_cifs/InAs_zb.cif" },
    { name: "InP", phase: "zinc-blende", a: 5.904, path: "/III-V/bulk_cifs/InP_zb.cif" },
    { name: "InSb", phase: "zinc-blende", a: 6.633, path: "/III-V/bulk_cifs/InSb_zb.cif" }
  ],
  "IV-VI": [
    { name: "PbS", phase: "rock-salt", a: 5.976, path: "/IV-VI/bulk_cifs/PbS_rs.cif" },
    { name: "PbSe", phase: "rock-salt", a: 6.182, path: "/IV-VI/bulk_cifs/PbSe_rs.cif" },
    { name: "PbTe", phase: "rock-salt", a: 6.542, path: "/IV-VI/bulk_cifs/PbTe_rs.cif" }
  ]
};

/** Template for a family/material (e.g. "II-VI", "CdSe"), or null. */
export function templateFor(family, material, phase = null) {
  const list = (bulkTemplates[family] || []).filter((t) => t.name.toLowerCase() === String(material).toLowerCase());
  return (phase && list.find((t) => t.phase === phase)) || list[0] || null;
}
