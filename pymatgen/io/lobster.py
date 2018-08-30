# coding: utf-8
# Copyright (c) Pymatgen Development Team.
# Distributed under the terms of the MIT License

from __future__ import division, unicode_literals

import re
import numpy as np
import warnings

from monty.io import zopen
from collections import defaultdict
from pymatgen.electronic_structure.core import Spin, Orbital
from pymatgen.io.vasp.outputs import Vasprun
from pymatgen.electronic_structure.dos import Dos, LobsterCompleteDos
from pymatgen.electronic_structure.cohp import CompleteIcohp


"""
Module for reading Lobster output files. For more information
on LOBSTER see www.cohp.de.
"""

__author__ = "Marco Esters, Janine George"
__copyright__ = "Copyright 2017, The Materials Project"
__version__ = "0.2"
__maintainer__ = "Marco Esters"
__email__ = "esters@uoregon.edu"
__date__ = "Dec 13, 2017"



class Cohpcar(object):
    """
    Class to read COHPCAR/COOPCAR files generated by LOBSTER.

    Args:
        are_coops: Determines if the file is a list of COHPs or COOPs.
          Default is False for COHPs.

        filename: Name of the COHPCAR file. If it is None, the default
          file name will be chosen, depending on the value of are_coops.


    .. attribute: cohp_data

         Dict that contains the COHP data of the form:
           {bond: {"COHP": {Spin.up: cohps, Spin.down:cohps},
                   "ICOHP": {Spin.up: icohps, Spin.down: icohps},
                   "length": bond length,
                   "sites": sites corresponding to the bond}
         Also contains an entry for the average, which does not have
         a "length" key.

    .. attribute: efermi

         The Fermi energy in eV.

    .. attribute: energies

         Sequence of energies in eV. Note that LOBSTER shifts the energies
         so that the Fermi energy is at zero.

    .. attribute: is_spin_polarized

         Boolean to indicate if the calculation is spin polarized.

    .. attribute: orb_res_cohp

        orb_cohp[label] = {bond_data["orb_label"]: {"COHP": {Spin.up: cohps, Spin.down:cohps},
                                                     "ICOHP": {Spin.up: icohps, Spin.down: icohps},
                                                     "orbitals": orbitals,
                                                     "length": bond lengths,
                                                     "sites": sites corresponding to the bond}}

    """

    def __init__(self, are_coops=False, filename=None):
        self.are_coops = are_coops
        if filename is None:
            filename = "COOPCAR.lobster" if are_coops \
                else "COHPCAR.lobster"

        with zopen(filename, "rt") as f:
            contents = f.read().split("\n")

        # The parameters line is the second line in a COHPCAR file. It
        # contains all parameters that are needed to map the file.
        parameters = contents[1].split()
        # Subtract 1 to skip the average
        num_bonds = int(parameters[0]) - 1
        self.efermi = float(parameters[-1])
        if int(parameters[1]) == 2:
            spins = [Spin.up, Spin.down]
            self.is_spin_polarized = True
        else:
            spins = [Spin.up]
            self.is_spin_polarized = False

        # The COHP data start in row num_bonds + 3
        data = np.array([np.array(row.split(), dtype=float)
                         for row in contents[num_bonds + 3:]]).transpose()
        self.energies = data[0]

        cohp_data = {"average": {"COHP": {spin: data[1 + 2 * s * (num_bonds + 1)]
                                          for s, spin in enumerate(spins)},
                                 "ICOHP": {spin: data[2 + 2 * s * (num_bonds + 1)]
                                           for s, spin in enumerate(spins)}}}
        orb_cohp = {}

        #the labeling had to be changed: there are more than one COHP for each atom combination
        #this is done to make the labeling consistent with ICOHPLIST.lobster
        bondnumber=0
        for bond in range(num_bonds):
            bond_data = self._get_bond_data(contents[3 + bond])

            label = str(bondnumber)

            orbs = bond_data["orbitals"]
            cohp = {spin: data[2 * (bond + s * (num_bonds + 1)) + 3]
                    for s, spin in enumerate(spins)}

            icohp = {spin: data[2 * (bond + s * (num_bonds + 1)) + 4]
                     for s, spin in enumerate(spins)}
            if orbs is None:
                bondnumber=bondnumber+1
                label = str(bondnumber)
                cohp_data[label] = {"COHP": cohp, "ICOHP": icohp,
                                    "length": bond_data["length"],
                                    "sites": bond_data["sites"]}

            elif label in orb_cohp:
                orb_cohp[label].update({bond_data["orb_label"]:
                                            {"COHP": cohp,
                                             "ICOHP": icohp,
                                             "orbitals": orbs,
                                             "length": bond_data["length"],
                                             "sites": bond_data["sites"]}})
            else:

                if label not in cohp_data:
                    bondnumber = bondnumber + 1
                    # present for Lobster versions older than Lobster 2.2.0
                    cohp_data[label] = {"COHP": None, "ICOHP": None,
                                        "length": bond_data["length"],
                                        "sites": bond_data["sites"]}
                orb_cohp[label] = {bond_data["orb_label"]: {"COHP": cohp,
                                                            "ICOHP": icohp,
                                                            "orbitals": orbs,
                                                            "length": bond_data["length"],
                                                            "sites": bond_data["sites"]}}


        self.orb_res_cohp = orb_cohp if orb_cohp else None
        self.cohp_data = cohp_data


    @staticmethod
    def _get_bond_data(line):
        """
        Subroutine to extract bond label, site indices, and length from
        a LOBSTER header line. The site indices are zero-based, so they
        can be easily used with a Structure object.

        Example header line: No.4:Fe1->Fe9(2.4524893531900283)
        Example header line for orbtial-resolved COHP:
            No.1:Fe1[3p_x]->Fe2[3d_x^2-y^2](2.456180552772262)

        Args:
            line: line in the COHPCAR header describing the bond.

        Returns:
            Dict with the bond label, the bond length, a tuple of the site
            indices, a tuple containing the orbitals (if orbital-resolved),
            and a label for the orbitals (if orbital-resolved).
        """

        orb_labs = ["s", "p_y", "p_z", "p_x", "d_xy", "d_yz", "d_z^2",
                    "d_xz", "d_x^2-y^2", "f_y(3x^2-y^2)", "f_xyz",
                    "f_yz^2", "f_z^3", "f_xz^2", "f_z(x^2-y^2)", "f_x(x^2-3y^2)"]

        line = line.rsplit("(", 1)
        #bondnumber = line[0].replace("->", ":").replace(".", ":").split(':')[1]
        length = float(line[-1][:-1])

        sites = line[0].replace("->", ":").split(":")[1:3]
        site_indices = tuple(int(re.split(r"\D+", site)[1]) - 1
                             for site in sites)

        #species = tuple(re.split(r"\d+", site)[0] for site in sites)
        #TODO: give that to cohp
        if "[" in sites[0]:
            orbs = [re.findall(r"\[(.*)\]", site)[0] for site in sites]
            orbitals = [tuple((int(orb[0]), Orbital(orb_labs.index(orb[1:]))))
                        for orb in orbs]
            orb_label = "%d%s-%d%s" % (orbitals[0][0], orbitals[0][1].name,
                                       orbitals[1][0], orbitals[1][1].name)

        else:
            orbitals = None
            orb_label = None

        # a label based on the species alone is not feasible, there can be more than one bond for each atom combination
        #label = "%s" % (bondnumber)

        bond_data = {"length": length, "sites": site_indices,
                     "orbitals": orbitals, "orb_label": orb_label}
        return bond_data


class Icohplist(object):
    """
    Class to read ICOHPLIST/ICOOPLIST files generated by LOBSTER (starting from version ).

    Args:
        are_coops: Determines if the file is a list of ICOHPs or ICOOPs.
          Defaults to False for ICOHPs.

        filename: Name of the ICOHPLIST file. If it is None, the default
          file name will be chosen, depending on the value of are_coops.


    .. attribute: are_coops
         Boolean to indicate if the populations are COOPs or COHPs.

    .. attribute: is_spin_polarized
         Boolean to indicate if the calculation is spin polarized.

    .. attribute: Icohplist
        Dict containing the listfile data of the form:
           {bond: "length": bond length,
                  "number_of_bonds": number of bonds
                  "icohp": {Spin.up: ICOHP(Ef) spin up, Spin.down: ...}}

    .. attribute: CompleteIcohp
        CompleteIcohp Object

    """

    def __init__(self, are_coops=False, filename=None):

        self.are_coops = are_coops
        if filename is None:
            filename = "ICOOPLIST.lobster" if are_coops \
                else "ICOHPLIST.lobster"

        # LOBSTER list files have an extra trailing blank line
        # and we don't need the header.
        with zopen(filename) as f:
            data = f.read().split("\n")[1:-1]
        if len(data) == 0:
            raise IOError("ICOHPLIST file contains no data.")

        # Which Lobster version?
        if len(data[0].split()) == 8:
            version = '3.1.1'
        elif len(data[0].split()) == 6:
            version = '2.2.1'
            warnings.warn('Please consider using the new Lobster version. See www.cohp.de.')
        else:
            raise ValueError

        # If the calculation is spin polarized, the line in the middle
        # of the file will be another header line.
        if "distance" in data[len(data) // 2]:
            num_bonds = len(data) // 2
            if num_bonds == 0:
                raise IOError("ICOHPLIST file contains no data.")
            self.is_spin_polarized = True
        else:
            num_bonds = len(data)
            self.is_spin_polarized = False


        list_labels=[]
        list_atom1=[]
        list_atom2=[]
        list_length=[]
        list_translation=[]
        list_num=[]
        list_icohp=[]
        for bond in range(num_bonds):
            line = data[bond].split()
            icohp = {}
            if version == '2.2.1':
                label = "%s" % (line[0])
                atom1 = str(line[1])
                atom2 = str(line[2])
                length = float(line[3])
                icohp[Spin.up] = float(line[4])
                num = int(line[5])
                translation = [0, 0, 0]
                if self.is_spin_polarized:
                    icohp[Spin.down] = float(data[bond + num_bonds + 1].split()[4])


            elif version == '3.1.1':
                label = "%s" % (line[0])
                atom1 = str(line[1])
                atom2 = str(line[2])
                length = float(line[3])
                translation = [int(line[4]), int(line[5]), int(line[6])]
                icohp[Spin.up] = float(line[7])
                num = int(1)

                if self.is_spin_polarized:
                    icohp[Spin.down] = float(data[bond + num_bonds + 1].split()[7])

            list_labels.append(label)
            list_atom1.append(atom1)
            list_atom2.append(atom2)
            list_length.append(length)
            list_translation.append(translation)
            list_num.append(num)
            list_icohp.append(icohp)

        self._icohpcollection = CompleteIcohp(are_coops=are_coops,list_labels=list_labels,list_atom1=list_atom1,list_atom2=list_atom2,list_length=list_length, list_translation=list_translation,list_num=list_num,list_icohp=list_icohp, is_spin_polarized=self.is_spin_polarized)

    @property
    def icohplist(self):
        """
        Returns: icohplist compatible with older version of this class
        """
        icohplist_new={}
        for key,value in self._icohpcollection._icohplist.items():
            icohplist_new[key]={"length": value._length, "number_of_bonds": value._num,
                                "icohp": value._icohp,"translation": value._translation}
        return icohplist_new
    @property
    def completeicohp(self):
        """
        Returns: CompleteIcohp object
        """
        return self._icohpcollection


class Doscar(object):
    """
    Class to deal with Lobster's projected DOS and local projected DOS.
    The beforehand quantum-chemical calculation was performed with VASP

    Args:
        doscar: DOSCAR filename, typically "DOSCAR.lobster"
        vasprun: vasprun filename, typically "vasprun.xml"

    .. attribute:: completedos

        LobsterCompleteDos Object

    .. attribute:: pdos
        List of Dict including numpy arrays with pdos. Access as pdos[atomindex]['orbitalstring']['Spin.up/Spin.down']

    .. attribute:: tdos
        Dos Object of the total density of states

    .. attribute:: energies
        numpy array of the energies at which the DOS was calculated (in eV, relative to Efermi)

    .. attribute:: tdensities
        tdensities[Spin.up]: numpy array of the total density of states for the Spin.up contribution at each of the energies
        tdensities[Spin.down]: numpy array of the total density of states for the Spin.down contribution at each of the energies

        if is_spin_polarized=False:
        tdensities[Spin.up]: numpy array of the total density of states

    .. attribute:: is_spin_polarized
        Boolean. Tells if the system is spin polarized


    """

    def __init__(self, doscar="DOSCAR.lobster", vasprun="vasprun.xml"):

        self._doscar = doscar
        self._vasprun = vasprun
        self._VASPRUN = Vasprun(filename=self._vasprun, ionic_step_skip=None,
                                ionic_step_offset=0, parse_dos=False,
                                parse_eigen=False, parse_projected_eigen=False,
                                parse_potcar_file=False, occu_tol=1e-8,
                                exception_on_bad_xml=True)
        self._final_structure = self._VASPRUN.final_structure
        self._is_spin_polarized = self._VASPRUN.is_spin
        self._parse_doscar()

    def _parse_doscar(self):
        doscar = self._doscar

        tdensities = {}
        f = open(doscar)
        natoms = int(f.readline().split()[0])
        efermi=float([f.readline() for nn in range(4)][3].split()[17])
        dos = []
        orbitals = []
        for atom in range(natoms + 1):
            line = f.readline()
            ndos = int(line.split()[2])
            orbitals.append(line.split(';')[-1].split())
            line = f.readline().split()
            cdos = np.zeros((ndos, len(line)))
            cdos[0] = np.array(line)
            for nd in range(1, ndos):
                line = f.readline().split()
                cdos[nd] = np.array(line)
            dos.append(cdos)
        f.close()

        doshere = np.array(dos[0])
        energies = doshere[:, 0]
        if not self._is_spin_polarized:
            tdensities[Spin.up] = doshere[:, 1]
            pdoss = []
            spin = Spin.up
            for atom in range(natoms):
                pdos = defaultdict(dict)
                data = dos[atom + 1]
                _, ncol = data.shape
                orbnumber = 0
                for j in range(1, ncol):
                    orb = orbitals[atom + 1][orbnumber]
                    pdos[orb][spin] = data[:, j]
                    orbnumber = orbnumber + 1
                pdoss.append(pdos)
        else:
            tdensities[Spin.up] = doshere[:, 1]
            tdensities[Spin.down] = doshere[:, 2]
            pdoss = []
            for atom in range(natoms):
                pdos = defaultdict(dict)
                data = dos[atom + 1]
                _, ncol = data.shape
                orbnumber = 0
                for j in range(1, ncol):
                    if j % 2 == 0:
                        spin = Spin.down
                    else:
                        spin = Spin.up
                    orb = orbitals[atom + 1][orbnumber]
                    pdos[orb][spin] = data[:, j]
                    if j % 2 == 0:
                        orbnumber = orbnumber + 1
                pdoss.append(pdos)
        self._efermi = efermi
        self._pdos = pdoss
        self._tdos = Dos(efermi, energies, tdensities)
        self._energies = energies
        self._tdensities = tdensities
        final_struct = self._final_structure

        pdossneu = {final_struct[i]: pdos for i, pdos in enumerate(self._pdos)}

        self._completedos = LobsterCompleteDos(final_struct, self._tdos, pdossneu)

    @property
    def completedos(self):
        return self._completedos

    @property
    def pdos(self):
        return self._pdos

    @property
    def tdos(self):
        return self._tdos

    @property
    def energies(self):
        return self._energies

    @property
    def tdensities(self):
        return self._tdensities

    @property
    def is_spin_polarized(self):
        return self._is_spin_polarized



class Charge(object):
    """Class to read CHARGE files generated by LOBSTER
        Args:
            filename: filename for the CHARGE file, typically "CHARGE.lobster"

        .. attribute: atomlist
            List of atoms in CHARGE.lobster
        .. attribute: types
            List of types of atoms in CHARGE.lobster
        .. attribute: Mulliken
            List of Mulliken charges of atoms in CHARGE.lobster
        .. attribute: Loewdin
            List of Loewdin charges of atoms in CHARGE.Loewdin
        .. attribute: num_atoms
            Number of atoms in CHARGE.lobster

    """

    def __init__(self, filename="CHARGE.lobster"):
        with zopen(filename) as f:
            data = f.read().split("\n")[3:-3]
        if len(data) == 0:
            raise IOError("CHARGES file contains no data.")

        self.num_atoms = len(data)
        self.atomlist = []
        self.types = []
        self.Mulliken = []
        self.Loewdin = []
        for atom in range(0, self.num_atoms):
            line = data[atom].split()
            self.atomlist.append(line[1] + line[0])
            self.types.append(line[1])
            self.Mulliken.append(float(line[2]))
            self.Loewdin.append(float(line[3]))

    def get_structure_with_charges(self,structure_filename):
        """
        get a Structure with Mulliken and Loewdin charges as site properties
        Args:
            structure_filename: filename of POSCAR
        Returns:
            Structure Object with Mulliken and Loewdin charges as site properties
        """

        struct=Structure.from_file(structure_filename)
        Mulliken=self.Mulliken
        Loewdin=self.Loewdin
        site_properties={"Mulliken Charges": Mulliken, "Loewdin Charges": Loewdin}
        new_struct=struct.copy(site_properties=site_properties)
        return new_struct

