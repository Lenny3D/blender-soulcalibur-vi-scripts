#!/usr/bin/env python3
from enum import Enum
from collections import namedtuple
from pathlib import Path
from typing import Any

import json
import os
import re

# Blender
import bpy

CHARA_MAT_RE = re.compile('[a-zA-Z]+_R0?([0-9]+)_[a-zA-Z0-9]+')
CHARA_DLC_MAP = {
    60: 1,  # 2B?
    30: 4,  # Cassandra?
    17: 6,  # Amy?
    28: 7,  # Hilde! Hilde! Hilde!
    61: 9,  # Hoahmaru?
    22: 11, # Setsuka
    9:  13  # Hwang
}

class ResourceType(Enum):
    UNKNOWN = 0
    INT = 1
    FLOAT = 2
    BOOL = 3
    ARRAY = 4
    CHARA_MAT = 5
    TEXTURE_2D = 6
    VECTOR_4 = 7
    
    @classmethod
    def fromString(cls, string: str):
        if string == "MaterialInstanceConstant":
            return cls.CHARA_MAT
        if string == "Material3":
            return cls.CHARA_MAT
        if string == "Texture2D":
            return cls.TEXTURE_2D
        return cls.UNKNOWN

class ResourceResolver:
    """Resolves the path to a resource"""
    basePath: Path
    
    def __init__(self, basePath = None):
        if basePath:
            self.basePath = basePath
        else:
            self.basePath = Path.home() / "UmodelExport"
    
    def resolveResourcePath(self, resType: ResourceType, name: str) -> Path:
        """Finds the path to a given resource"""
        if "/" in name:
            path: Path = Path(self.basePath, name)
            
            if path.stem == path.suffix[1:]:
                if resType == ResourceType.TEXTURE_2D:
                    path = path.with_suffix(".tga")
                elif resType == ResourceType.CHARA_MAT:
                    path = path.with_suffix(".props.json")
                else:
                    print("Suffix same as stem, unknown file type")

            if path.exists():
                return path
        else:
            paths: list[Path] = [Path("Common/BasicResource")]
            if resType == ResourceType.CHARA_MAT:
                characterId: int = 0
                dlcNo: int = 0
                
                paths += [Path("Chara/CMN/Material")]
                
                m = CHARA_MAT_RE.match(name)
                if m:
                    characterId = int(m.group(1))
                    # FIXME: check which characters are actually DLC
                    if characterId in CHARA_DLC_MAP:
                        dlcNo = CHARA_DLC_MAP[characterId]
                        paths += [Path("DLC/{0:0>2}/Chara/{1:0>3}/Material".format(dlcNo, characterId))]
                    else:
                        dlcNo = 0
                        paths += [Path("Chara/{0:0>3}/Material".format(characterId))]
                
                for path in paths:
                    matPath: Path = Path(self.basePath, path, name + ".props.json")
                    if matPath.exists():
                        return matPath
            
        return None
    
    def readResource(self, resType: ResourceType, name: str) -> str:
        """Reads a resource to a string"""
        path = self.resolveResourcePath(resType, name)
        if not path:
            print("Could not find resource {0} of type {1}".format(name, resType))
            return None
        with open(path, "r") as f:
            return f.read()



class Property:
    """The type of this property"""
    propertyType: ResourceType
    value: Any = None
    
    def __init__(self, value: Any = None, propertyType: ResourceType = ResourceType.UNKNOWN):
        self.propertyType = propertyType
        self.value = value
        
    def __repr__(self):
        return "{0} ({1})".format(self.value, self.propertyType)

class PropertyFile:
    resourceResolver: ResourceResolver
    contents: str
    
    properties: dict[str, Property] = {}
    parent: Property = None
    
    def __init__(self, contents: str, resourceResolver: ResourceResolver):
        """Creates a property file from a path"""
        self.resourceResolver = resourceResolver
        self.contents = contents
    
    def parse(self) -> None:
        """Parses the properties out of the contents into this string"""
        data = json.loads(self.contents)
        
        for propName, propValue in data.items():
            if propName == "Parent":
                self.parent = self.parseProperty(data["Parent"])
            if "ParameterValues" in propName:
                typeName, _ = propName.split("ParameterValues")
                
                resType: ResourceType = ResourceType.UNKNOWN
                
                # Workaround for empty property values that are generated with a "{}" string
                if type(propValue) is str and propValue == "{}":
                    continue
                
                if typeName == "Scalar":
                    for param in propValue:
                        self.properties[param["ParameterName"]] = Property(float(param["ParameterValue"]), ResourceType.FLOAT)
                elif typeName == "Texture":
                    for param in propValue:
                        self.properties[param["ParameterName"]] = self.parseProperty(param["ParameterValue"])
                elif typeName == "Vector":
                    for param in propValue:
                        values = param["ParameterValue"]
                        self.properties[param["ParameterName"]] = Property([float(values["R"]), 
                                                                            float(values["G"]),
                                                                            float(values["B"]),
                                                                            float(values["A"])],
                                                                            ResourceType.VECTOR_4) 
                else:
                    print("Discarded property of type {0}".format(typeName))
    
    def build(self) -> None:
        """Parses the file and merges it with its parents"""
        self.parse()
        self.mergeWithParents()
    
    def parseProperty(self, value: Any, typeHint: ResourceType = ResourceType.UNKNOWN) -> Property:
        if type(value) is str and value.endswith("'"):
            typeName, propertyValue, _ = value.split("'")
            return Property(propertyValue, ResourceType.fromString(typeName))
        
        return Property(value, typeHint)
    
    
    def mergeWithParents(self) -> None:
        """Merges all parent properties into this file"""
        if self.parent:
            parent: PropertyFile = PropertyFile(self.resourceResolver.readResource(self.parent.propertyType, self.parent.value), 
                                                self.resourceResolver)
            parent.build()
            for propName, propValue in parent.properties.items():
                if propName not in self.properties:
                    self.properties[propName] = propValue

def register() -> None:
    pass

###########################################################################################
# Material                                                                                #
###########################################################################################

def get_creation_mask_node(forceCreate: bool = False) -> bpy.types.ShaderNodeGroup:
    if not forceCreate or "CREATION_MASK" in bpy.data.node_groups:
        return bpy.data.node_groups["CREATION_MASK"]
    
    
    node_tree = bpy.data.node_groups.new(name = "CREATION_MASK", type = "ShaderNodeTree")
    node_tree.clear()
    nodes = node_tree.nodes
    
    # Inputs/outputs
    return nodes
    

def setup_materials():
    r: ResourceResolver = ResourceResolver()
    
    def create_texture_node(prop: Property) -> bpy.types.ShaderNodeTexImage:
        node = nodes.new("ShaderNodeTexImage")
        img_path = r.resolveResourcePath(prop.propertyType, prop.value)
        node.image = bpy.data.images.load(bytes(img_path), check_existing=True)
        return node
        
    
    for name, mat in bpy.data.materials.items():
        print("Loading {0}".format(name))
        data = r.readResource(ResourceType.CHARA_MAT, name)
        if data:
            p: PropertyFile = PropertyFile(data, r)
            p.build()
            print(repr(p.properties))
            
            mat.use_nodes = True
            
            nodes = mat.node_tree.nodes
            nodes.clear()
            bsdf_node = nodes.new('ShaderNodeBsdfPrincipled')
            bsdf_node.location = (0,0)
            output_node = nodes.new('ShaderNodeOutputMaterial')
            output_node.location = (500,0)
                
            mat.node_tree.links.new(bsdf_node.outputs[0], output_node.inputs[0])
            
            if "Anisotropy" in p.properties:
                bsdf_node.inputs["Anisotropic"].default_value = p.properties["Anisotropy"].value
            
            if "Metallic" in p.properties:
                bsdf_node.inputs["Metallic"].default_value = p.properties["Metallic"].value
                
            if "IoR" in p.properties:
                bsdf_node.inputs["IOR"].default_value = p.properties["IoR"].value
            
            if "BaseColor" in p.properties:
                base_color_node = create_texture_node(p.properties["BaseColor"])
                
                mat.node_tree.links.new(base_color_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])
                if "CreationMask" in p.properties:
                    # Creates a group of nodes that replaces the color of the mask with another color
                    base_color_node.location = (-4000, -300)
                    creation_mask_node = create_texture_node(p.properties["CreationMask"])
                    creation_mask_node.label = "Creation Mask"
                    creation_mask_node.location = (-4000, 0)
                    
                    creation_mask_split_node = nodes.new("ShaderNodeSeparateRGB")
                    mat.node_tree.links.new(creation_mask_node.outputs["Color"], creation_mask_split_node.inputs["Image"])
                    creation_mask_split_node.location = (-3500, 0)
                    
                    creation_valid_mask = p.properties["CreationValidMask"].value
                    prev_color_node = base_color_node
                    
                    for i, valid in enumerate(creation_valid_mask):
                        if valid != 0.0:
                            color_node = nodes.new("ShaderNodeRGB")
                            color_node.location =  (-3500 + 500 * i, -600 )
                            color_node.label = "Creation color {0}".format(i + 1)
                            color = p.properties["CreationColor{0}".format(i + 1)].value
                            color_node.outputs["Color"].default_value = color
                            
                            math_node = nodes.new("ShaderNodeMath")
                            math_node.location = (-3000 + 500 * i, 300 )
                            math_node.operation = "MULTIPLY"
                            
                            mul_node = nodes.new("ShaderNodeMixRGB")
                            mul_node.location =  (-3000 + 500 * i, -300 )
                            mul_node.blend_type = "MULTIPLY"
                            mul_node.inputs["Fac"].default_value = 1.0
                            
                            mix_node = nodes.new("ShaderNodeMixRGB")
                            mix_node.location =  (-2500 + 500 * i, 0 )
                            #if "IsSkin" in p.properties and p.properties["IsSkin"] != 0.0:
                            mix_node.blend_type = "MIX"
                            
                            mat.node_tree.links.new(base_color_node.outputs["Color"], mul_node.inputs["Color1"])
                            mat.node_tree.links.new(color_node.outputs[0], mul_node.inputs["Color2"])
                            mat.node_tree.links.new(creation_mask_node.outputs["Alpha"], math_node.inputs[1])
                            mat.node_tree.links.new(math_node.outputs[0], mix_node.inputs["Fac"])
                            mat.node_tree.links.new(prev_color_node.outputs["Color"], mix_node.inputs["Color1"])
                            mat.node_tree.links.new(mul_node.outputs["Color"], mix_node.inputs["Color2"])
                            
                            if i == 0:
                                # Colour 1 replaces the red channel
                                mat.node_tree.links.new(creation_mask_split_node.outputs["R"], math_node.inputs[0])
                            elif i == 3:
                                # Colour 2 replaces the blue channel
                                mat.node_tree.links.new(creation_mask_split_node.outputs["B"], math_node.inputs[0])
                            elif i == 2:
                                # Colour 3 replaces the green channel
                                mat.node_tree.links.new(creation_mask_split_node.outputs["G"], math_node.inputs[0])
                            elif i == 1:
                                # Colour 4 replaces black
                                
                                # Determine if something is black by checking if every element is 0
                                length_node = nodes.new("ShaderNodeVectorMath")
                                length_node.location = (-3500 + 500 * i, 500 )
                                length_node.operation = "LENGTH"
                                
                                cmp_node = nodes.new("ShaderNodeMath")
                                cmp_node.location = (-3250 + 500 * i, 500 )
                                cmp_node.operation = "COMPARE"
                                cmp_node.inputs[1].default_value = 0.0
                                
                                mat.node_tree.links.new(creation_mask_node.outputs["Color"], length_node.inputs["Vector"])
                                mat.node_tree.links.new(length_node.outputs["Value"], cmp_node.inputs[0])
                                mat.node_tree.links.new(cmp_node.outputs[0], math_node.inputs[0])
                            
                            prev_color_node = mix_node
                            
                    mat.node_tree.links.new(prev_color_node.outputs["Color"], bsdf_node.inputs["Base Color"])
                else:
                    # If there is no creation mask, connect it directly to the bsdf node
                    base_color_node.location = (-1000, 0)
                    mat.node_tree.links.new(base_color_node.outputs["Color"], bsdf_node.inputs["Base Color"])
            
            if "NormalMap" in p.properties:
                normal_map_node = create_texture_node(p.properties["NormalMap"])
                normal_map_node.location = (-500, -500)
                mat.node_tree.links.new(normal_map_node.outputs["Color"], bsdf_node.inputs["Normal"])
                
            if "ParameterMap" in p.properties:
                # http://modderbase.com/showthread.php?tid=1878
                # Red Channel: Specular
                # Green Channel: Roughness
                # Blue Channel: Metalness
                # Alpha Channel: ???
                param_map_node = create_texture_node(p.properties["ParameterMap"])
                param_map_node.location = (-600, -250)
                param_map_split_node = nodes.new("ShaderNodeSeparateRGB")
                param_map_split_node.location = (-250, -200)
                
                mat.node_tree.links.new(param_map_node.outputs["Color"],   param_map_split_node.inputs["Image"])
                mat.node_tree.links.new(param_map_split_node.outputs["R"], bsdf_node.inputs["Specular"])
                mat.node_tree.links.new(param_map_split_node.outputs["G"], bsdf_node.inputs["Roughness"])
                mat.node_tree.links.new(param_map_split_node.outputs["B"], bsdf_node.inputs["Metallic"])
                mat.node_tree.links.new(param_map_node.outputs["Alpha"],   bsdf_node.inputs["Anisotropic"])
               

if __name__ == "__main__":
    setup_materials()