"""
utilities
"""
import os
import MDAnalysis as mda
import mdtraj as md
import argparse
from PeptideBuilder import Geometry
import PeptideBuilder
import Bio.PDB
import simtk.unit as unit
from simtk.openmm.app import *
import time
from pdbfixersource import PDBFixer
import numpy as np
from shutil import copyfile
import csv


# I/O
def get_input():
    """
    get the command line in put for the run num. defaulting to a new run (0)
    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--run_num', type=int, default=0)
    parser.add_argument('--sequence', type=str, default='XXX')
    parser.add_argument('--peptide', type=str, default='BBB')
    parser.add_argument('--walltime', type=float, default=24)
    cmd_line_input = parser.parse_args()
    run = cmd_line_input.run_num
    sequence = cmd_line_input.sequence
    peptide = cmd_line_input.peptide
    walltime = cmd_line_input.walltime

    return [run, sequence, peptide, walltime]

def writeCheckpoint(text):
    """
    write some output to the checkpoint file
    :return:
    """
    f = open('checkpoint.txt', 'a')
    f.write('\n' + text)
    f.close()

class Timer:
    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        self.end = time.time()
        self.interval = self.end - self.start

def printRecord(statement):
    '''
    print a string to command line output and a text file
    :param statement:
    :return:
    '''
    print(statement)
    if os.path.exists('record.txt'):
        with open('record.txt', 'a') as file:
            file.write('\n' + statement)
    else:
        with open('record.txt', 'w') as file:
            file.write('\n' + statement)


# pdb & dcd file editing
def prepPDB(file, boxOffset, pH, ionicStrength, MMBCORRECTION=False, waterBox=True):
    """
    soak pdb file in water box
    :MMBCORRECTION: if the input pdb file is an MMB output, we need to apply a correction, since MMB is a little weird formatting-wise https://simtk.org/plugins/phpBB/viewtopicPhpbb.php?f=359&t=13397&p=0&start=0&view=&sid=bc6c1b9005122914ec7d572999ba945b
    :param file:
    :return:
    """
    if MMBCORRECTION:
        replaceText(file, '*', "'")  # due to a bug in this version of MMB - structures are encoded improperly - this fixes it

    fixer = PDBFixer(filename=file)
    padding, boxSize, boxVectors = None, None, None
    geompadding = float(boxOffset) * unit.nanometer

    boxMode = 'cubic' # toggle for box type - look at openmm-setup source code for other box types

    if boxMode == 'cubic':
        padding = geompadding # for cubic box
    elif boxMode == 'rectangular prism':
        # or we can make a rectangular prism which (maybe) cuts off sides of the cube
        u = mda.Universe(file)
        coords = u.atoms.positions
        xrange = np.ptp(coords[:, 0]) # get the maximum dimension
        yrange = np.ptp(coords[:, 1])
        zrange = np.ptp(coords[:, 2])
        maxsize = max([xrange, yrange, zrange])
        xrange = max([xrange,maxsize/2]) / 10 # minimum dimension is half the longest, also convert to nm
        yrange = max([yrange,maxsize/2]) / 10
        zrange = max([zrange,maxsize/2]) / 10

        xrange = xrange + 2 * boxOffset  # may also need an EWALD offset
        yrange = yrange + 2 * boxOffset
        zrange = zrange + 2 * boxOffset

        boxSize = [xrange,yrange,zrange] * unit.nanometer # for rectangular prism

    fixer.findMissingResidues()
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()  # may need to optimize bonding here

    fixer.addMissingHydrogens(pH=pH)  # add missing hydrogens

    if waterBox == True:
        ionicStrength = float(ionicStrength) * unit.molar  # not implemented
        positiveIon = 'Na+'  # params['positiveion']+'+'
        negativeIon = 'Cl-'  # params['negativeion']+'-'
        fixer.addSolvent(boxSize, padding, boxVectors, positiveIon, negativeIon, ionicStrength)

    PDBFile.writeFile(fixer.topology, fixer.positions, open(file.split('.pdb')[0] + '_processed.pdb', 'w'))

def findAngles():
    """
    Reads the angles required to constrain the dihedrals of the peptide backbone from the backbone_dihedrals.csv file. 
    For more info, see README_CONSTRAINTS.md
    :param:
    :return angles_to_constrain, a list that contains the numerical values for angles to constrain:
    """
    angles_to_constrain = []
    resdict = {"ALA": "A","CYS": "C","ASP": "D","GLU": "E","PHE": "F",
               "GLY": "G","HIS": "H","ILE": "I","LYS": "K","LEU": "L",
               "MET": "M","ASN": "N","PRO": "P","GLN": "Q","ARG": "R",
               "SER": "S","THR": "T","VAL": "V","TRP": "W","TYR": "Y"}
    resdict_inv = {one_let: three_let for three_let, one_let in resdict.items()} # 3-letter a.a. code easier to work with for OpenMM

    with open("backbone_dihedrals.csv", r) as csv_file:
        read_csv = csv.reader(csv_file, delimiter=",")
        rows = []
        row_lengths = set()
        
        for row in read_csv:
            rows.append(row)
            row_lengths.add(len(row))

        if len(rows) == 1 and params['peptide backbone constraint constant'] != 0:
            printRecord("ERROR: Backbone angles file does not have any values, but the constraint constant in main.py is not zero. Exiting run.")
            exit()
    
        if len(row_lengths) != 1:   # won't work if there is 1 more faulty input for line 1, and 4 inputs for line 2
            rows_unequal = []

            for i in range(len(rows)):
                if len(rows[i]) != 3:
                    rows_unequal.append(i + 1)

            printRecord("ERROR: Incorrect number of inputs for rows:")
            for i, unequal_row in enumerate(rows_unequal):
                if i == len(rows_unequal) - 1:
                    printRecord(unequal_row)
                elif i == len(rows_unequal) - 2:
                    printRecord(unequal_row)
                else:
                    printRecord(unequal_row)
            
            printRecord("Exiting run.")
            exit()

        elif len(row_lengths) == 1 and list(row_lengths)[0] == 3 and len(rows) > 1:  # everything is correct here
            angles_to_constrain = []

            for i in range(len(rows)):
                if i > 0:
                    angles_to_constrain.append(rows[i])

            return angles_to_constrain
         
#         if len(row_lengths) != 1:
#             printRecord("ERROR: Backbone angles file is contains

#         elif len(rows) != 0 and params['peptide backbone constraint constant'] == 0:
#             printRecord("WARNING: Backbone angles file is not empty, but the constraint constant in main.py is zero")
    
#     for amino_acid in peptide:
#         geo = Geometry.geometry(amino_acid)
        
#         da_set = geo.phi, geo.psi_im1, geo.omega # the set (actually a tuple) of 3 dihedral angles in the amino acid (from N- to C-terminus)
#         angles_to_constrain[resdict_inv[amino_acid]] = [da * np.pi / 180 for da in da_set]
        
#     return angles_to_constrain
    

def buildPeptide(peptide, customAngles=False):
    """
    construct a peptide sequence pdb file
    :param peptide:
    :return:
    """
    geo = Geometry.geometry(peptide[0])    
    phis, psis = [row[1] for row in angles_to_constrain], [row[2] for row in angles_to_constrain]
    
    if customAngles:
        for row in angles_to_constrain:
            if row[0] == 0: 
                geo.phi = phis[0]
                geo.psi = psis[0]
    
    structure = PeptideBuilder.initialize_res(peptide[0])
    
    for i in range(1, len(peptide)):
        geo = Geometry.geometry(peptide[i])
        
        if customAngles:
            for row in angles_to_constrain:
                if row[0] == i:
                    geo.phi = phis[i]
                    geo.psi = psis[i]
        
        PeptideBuilder.add_residue(structure, geo)
            
    PeptideBuilder.add_terminal_OXT(structure) # OpenMM will not run without this, but LightDock will not run with it. Solution, add terminal oxygen in prepPDB after docking

    out = Bio.PDB.PDBIO()
    out.set_structure(structure)
    out.save('peptide.pdb')

def combinePDB(file1, file2):
    """
    combine 2 pdb files into one
    some special formatting for MDA outputs in particular
    :param file1:
    :param file2:
    :return:
    """
    filenames = [file1, file2]
    for file in filenames:  # remove title, periodic box, endpoints
        removeLine(file, 'CRYST1')
        removeLine(file, 'TITLE')
        removeLine(file, 'END')
        if 'repStructure' in file:
            appendLine(file, 'TER')

    with open('combined.pdb', 'w') as outfile:
        for fname in filenames:
            with open(fname) as infile:
                for line in infile:
                    outfile.write(line)

def cleanTrajectory(structure, trajectory):
    """
    remove water, salt from trajectory input
    :param structure: pdb input for initial structure template
    :param trajectory: dcd trajectory file
    :return:
    """
    u = mda.Universe(structure, trajectory)  # load up trajectory
    goodStuff = u.segments[:-2].atoms  # cut out salts and solvent
    goodStuff.write("clean_" + structure)  # write topology
    with mda.Writer("clean_" + trajectory, goodStuff.n_atoms) as W:  # and write trajectory
        for ts in u.trajectory:  # indexing over the trajectory
            W.write(goodStuff)

# noinspection PyStatementEffect
def extractFrame(structure, trajectory, frame, outFileName):
    """
    saves a given trajectory frame as a separate pdb file
    :param structure: pdb input for initial structure template
    :param trajectory: dcd trajectory file
    :param frame: frame to be extracted
    :param outFileName: the name of the output file
    :return:
    """
    u = mda.Universe(structure, trajectory)  # load up trajectory
    u.trajectory[frame]  # this indexes the trajectory up to the desired frame (weird syntax, I think)
    if u.segments.n_segments > 2:  # if there are more than 2 segments, then there must be solvent and salts (assuming nonzero salt concentration)
        atoms = u.segments[:-2].atoms  # omit solvent and salts
    else:
        atoms = u.atoms
    atoms.write(outFileName)

def recenterDCD(topology, trajectory):
    """
    topology as pdb
    trajectory as dcd
    creates a new dcd without periodic artifacts
    """
    traj = md.load(trajectory, top = topology)
    traj.image_molecules()
    traj.save(trajectory.split('.')[0] + '_recentered.dcd')

def killH(structure):
    """
    use simTk modeller to delete all atoms with 'H' in the name
    """
    pdb = PDBFile(structure)
    topology = pdb.topology
    positions = pdb.positions
    modeller = Modeller(topology, positions)
    modeller.delete(atom for atom in topology.atoms() if "H" in atom.name)
    PDBFile.writeFile(modeller.topology, modeller.positions, open(structure.split('.')[0] + '_noH.pdb', 'w'))

def changeSegment(structure, oldSeg, newSeg):
    """
    change the segment ID for all molecule(s) in a pdb file
    """
    replaceText(structure, ' ' + oldSeg + ' ', ' ' + newSeg + ' ')

def addH(structure, pH):
    """
    protonate a given structure
    :param file:
    :return:
    """
    pdb = PDBFile(structure)
    topology = pdb.topology
    positions = pdb.positions
    modeller = Modeller(topology, positions)
    modeller.addHydrogens(pH=pH)
    PDBFile.writeFile(modeller.topology, modeller.positions, open(structure.split('.')[0] + '_H.pdb', 'w'))

def appendTrajectory(topology, original, new):
    """
    use mda to combine old and new MD trajectory files
    """
    trajectories = [original, new]
    u = mda.Universe(topology, trajectories)
    with mda.Writer('combinedTraj.dcd', u.atoms.n_atoms) as W:
        for ts in u.trajectory:
            W.write(u)

def fullPipelineTrajectory(ind1,ind2):
    '''
    combine folding, smoothing, sampling, docking and binding trajectories into one nice video
    '''

    # this needs to be updated with the new file formatting system
    trajectories = []
    # fold
    dir = './mmbFiles_%d'%ind1
    copyfile(dir + '/last.1.pdb','foldFrame1.pdb')
    dirList = os.listdir(dir)

    filenames = []
    for file in dirList:
        if 'trajectory' in file:
            filenames.append(dir + '/' +file)

    with open('foldingTraj_%d'%ind1 + '.pdb', 'w') as outfile:
        for fname in filenames:
            with open(fname) as infile:
                for line in infile:
                    outfile.write(line)

    replaceText('foldingTraj_%d'%ind1 + '.pdb', '*', "'")  # due to a bug in this version of MMB - structures are encoded improperly - this fixes it

    u = mda.Universe('foldingTraj_%d'%ind1 + '.pdb')
    with mda.Writer('foldingTraj_%d'%ind1 +'.dcd', u.atoms.n_atoms) as W:
        for ts in u.trajectory:
            W.write(u)

    trajectories.append('foldingTraj_%d'%ind1 + '.dcd')

    # initial relaxation
    trajectories.append('smoothed_sequence_%d'%ind1 + '.dcd')

    # free aptamer
    trajectories.append('clean_finished_sequence_%d'%ind1 + '.dcd')

    u = mda.Universe('foldFrame1.pdb', trajectories)

    with mda.Writer('fullPipeTraj.dcd', u.atoms.n_atoms) as W:
        for ts in u.trajectory:
            W.write(u)


    # docking

    # binding
    trajectories.append('clean_finished_complex_%d'%ind1 + '_%d'%ind2 + '.dcd')


# text editors
def findLine(file, string):
    # return the line number of a given string in a text file, indexing from 1
    f = open(file, 'r')
    text = f.read()
    f.close()
    text = text.split('\n')
    try:
        lineInd = 1
        for line in text:
            if line == string:
                lineNum = lineInd  # index from 1
            lineInd += 1

        return lineNum
    except:
        raise ValueError("String not found in file!")

def readFinalLines(file, lines):
    # return the final N lines of a text file
    f = open(file, 'r')
    text = f.read()
    f.close()
    text = text.split('\n')
    finalLines = text[-(lines + 1):]

    return finalLines

def readInitialLines(file, lines):
    # return the first N lines of a text file
    f = open(file, 'r')
    text = f.read()
    f.close()
    text = text.split('\n')
    initialLines = text[:lines]

    return initialLines

def replaceText(file, old_string, new_string):
    # search and replace text in a text file, then save the new version
    f = open(file, 'r')
    text = f.read()
    f.close()
    text = text.replace(old_string, new_string)
    f = open(file, 'w')
    f.write(text)
    f.close()

def copyLine(file, line_number):
    # copy a line of text from a file and return it
    f = open(file, 'r')
    text = f.read()
    f.close()
    return text.split('\n')[line_number - 1]  # copy a line from the file, indexing from 1

def removeLine(file, string):
    """
    remove every line containing given string from a file
    :param file: the file
    :param string: the string to look for
    :return:
    """
    f = open(file, 'r')
    text = f.read()
    f.close()
    lines = text.split('\n')
    try:
        for i in range(len(lines)):
            if string in lines[i]:
                lines.pop(i)
    except:
        pass
    text = "\n".join(lines)
    f = open(file, 'w')
    f.write(text)
    f.close()

def addLine(file, string, line_number):
    # add a new line of text to a file
    f = open(file, 'r')
    text = f.read()
    f.close()
    lines = text.split('\n')
    lines.insert(line_number - 1, string)  # replace line ### with the string, indexing from 1
    text = "\n".join(lines)
    f = open(file, 'w')
    f.write(text)
    f.close()

def appendLine(file, string):
    # add a new line of end of a file
    f = open(file, 'r')
    text = f.read()
    f.close()
    lines = text.split('\n')
    lines.insert(len(lines) - 1, string)  # replace line ### with the string, indexing from 1
    text = "\n".join(lines)
    f = open(file, 'w')
    f.write(text)
    f.close()

