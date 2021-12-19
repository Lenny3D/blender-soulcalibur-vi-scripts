#!/usr/bin/env python3

# Copyright (c) 2021 Lenny3D
#
# This software is provided 'as-is', without any express or implied
# warranty. In no event will the authors be held liable for any damages
# arising from the use of this software.

# Permission is granted to anyone to use this software for any purpose,
# including commercial applications, and to alter it and redistribute it
# freely, subject to the following restrictions:
# 
# 1. The origin of this software must not be misrepresented; you must not
#    claim that you wrote the original software. If you use this software
#    in a product, an acknowledgment in the product documentation would be
#    appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must not be
#    misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source distribution.

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
    # Character number: DLC number
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
                    
            elif resType == ResourceType.TEXTURE_2D:
                paths += [Path("Chara/CMN/Texture")]
                for path in paths:
                    texPath: Path = Path(self.basePath, path, name + ".tga")
                    if texPath.exists():
                        return texPath
            
            
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
            
            def add_properties(typeName: str, nameKey: str, valueKey: str) -> None:
                # Workaround for empty property values that are generated with a "{}" string
                if type(propValue) is str and propValue == "{}":
                    return
                if typeName == "Scalar":
                    for param in propValue:
                        param_name = param[nameKey]
                        param_value = param[valueKey]
                        
                        self.properties[param_name] = Property(float(param_value), ResourceType.FLOAT)
                elif typeName == "Texture":
                    for param in propValue:
                        param_name = param[nameKey]
                        param_value = param[valueKey]
                        
                        self.properties[param_name] = self.parseProperty(param_value)
                elif typeName == "Vector":
                    for param in propValue:
                        param_name = param[nameKey]
                        param_value = param[valueKey]
                        
                        self.properties[param_name] = Property([float(param_value["R"]), 
                                                                float(param_value["G"]),
                                                                float(param_value["B"]),
                                                                float(param_value["A"])],
                                                               ResourceType.VECTOR_4)
                else:
                    print("Discarded property of type {0}".format(typeName))
            if propName == "Parent":
                self.parent = self.parseProperty(data["Parent"])
            elif "ParameterValues" in propName:
                typeName, _ = propName.split("ParameterValues")
                add_properties(typeName, "ParameterName", "ParameterValue")
                    
            elif propName.startswith("Collected") and propName.endswith("Parameters"):
                # Handle CollectedXParameters
                typeName = propName[len("Collected"):-len("Parameters")]
                #if typeName == "Texture":
                #    add_properties(typeName, "Name", "Texture")
                #else:
                #    add_properties(typeName, "Name", "Value")
                

    
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
        #print(repr(self.properties))
        if self.parent:
            parent: PropertyFile = PropertyFile(self.resourceResolver.readResource(self.parent.propertyType, self.parent.value), 
                                                self.resourceResolver)
            parent.build()
            #print(self.parent.value))
            for parentPropName, parentPropValue in parent.properties.items():
                if parentPropName in self.properties:
                    pass
                    #print("    {0}: {1}, parent: {2} (overridden)".format(parentPropName, self.properties[parentPropName], parentPropValue))
                else:
                    self.properties[parentPropName] = parentPropValue
                    #print("    {0}: {1} (inherited)".format(parentPropName, parentPropValue))

def register() -> None:
    pass

###########################################################################################
# Material                                                                                #
###########################################################################################

def get_creation_mask_node(forceCreate: bool = False) -> bpy.types.ShaderNodeGroup:
    if "CREATION_MASK" in bpy.data.node_groups:
        if forceCreate:
            bpy.data.node_groups.remove(bpy.data.node_groups["CREATION_MASK"])
        else:
            return bpy.data.node_groups["CREATION_MASK"]
    
    node_tree = bpy.data.node_groups.new(name = "CREATION_MASK", type = "ShaderNodeTree")
    nodes = node_tree.nodes
    nodes.clear()
    
    # Inputs/outputs
    group_input = nodes.new("NodeGroupInput")
    group_input.location = (-3000, 0)
    group_output = nodes.new("NodeGroupOutput")
    group_output.location = (300, 0)
    
    node_tree.inputs.clear()
    node_tree.outputs.clear()
    
    base_color_input = node_tree.inputs.new("NodeSocketColor", "Base Color")
    creation_mask_input = node_tree.inputs.new("NodeSocketColor", "Creation Mask")
    creation_mask_input = node_tree.inputs.new("NodeSocketFloat", "Creation Mask Alpha")
    creation_color1_input = node_tree.inputs.new("NodeSocketColor", "Color 1")
    creation_color2_input = node_tree.inputs.new("NodeSocketColor", "Color 2")
    creation_color3_input = node_tree.inputs.new("NodeSocketColor", "Color 3")
    creation_color4_input = node_tree.inputs.new("NodeSocketColor", "Color 4")
    
    color_output = node_tree.outputs.new("NodeSocketColor", "Color")
    
    # Nodes
    creation_mask_split_node = nodes.new("ShaderNodeSeparateRGB")
    node_tree.links.new(group_input.outputs["Creation Mask"], creation_mask_split_node.inputs["Image"])
    creation_mask_split_node.location = (-2500, 150)
    
    prev_color_node = group_input
    
    for i in range(4):
        math_node = nodes.new("ShaderNodeMath")
        math_node.location = (-2000 + 500 * i, 300 )
        math_node.operation = "MULTIPLY"
        
        mul_node = nodes.new("ShaderNodeMixRGB")
        mul_node.location =  (-2000 + 500 * i, -300 )
        mul_node.blend_type = "MULTIPLY"
        mul_node.inputs["Fac"].default_value = 1.0
        
        mix_node = nodes.new("ShaderNodeMixRGB")
        mix_node.location =  (-1500 + 500 * i, 0 )
        #if "IsSkin" in p.properties and p.properties["IsSkin"] != 0.0:
        mix_node.blend_type = "MIX"
        
        node_tree.links.new(group_input.outputs["Base Color"], mul_node.inputs["Color1"])
        node_tree.links.new(group_input.outputs["Color {0}".format(i + 1)], mul_node.inputs["Color2"])
        node_tree.links.new(group_input.outputs["Creation Mask Alpha"], math_node.inputs[1])
        node_tree.links.new(math_node.outputs[0], mix_node.inputs["Fac"])
        
        color_output_name = "Color"
        if prev_color_node == group_input:
            color_output_name = "Base Color"
            
        node_tree.links.new(prev_color_node.outputs[color_output_name], mix_node.inputs["Color1"])
        node_tree.links.new(mul_node.outputs["Color"], mix_node.inputs["Color2"])
        
        if i == 0:
            # Colour 1 replaces red
            node_tree.links.new(creation_mask_split_node.outputs["R"], math_node.inputs[0])
        elif i == 3:
            # Colour 2 replaces black
            node_tree.links.new(creation_mask_split_node.outputs["B"], math_node.inputs[0])
        elif i == 2:
            # Colour 3 replaces green
            node_tree.links.new(creation_mask_split_node.outputs["G"], math_node.inputs[0])
        elif i == 1:
            # Colour 4 replaces blue
            
            # Determine if something is black by checking if every element is 0
            length_node = nodes.new("ShaderNodeVectorMath")
            length_node.location = (-2500 + 500 * i, 500 )
            length_node.operation = "LENGTH"
            
            cmp_node = nodes.new("ShaderNodeMath")
            cmp_node.location = (-2250 + 500 * i, 500 )
            cmp_node.operation = "COMPARE"
            cmp_node.inputs[1].default_value = 0.0
            
            node_tree.links.new(group_input.outputs["Creation Mask"], length_node.inputs["Vector"])
            node_tree.links.new(length_node.outputs["Value"], cmp_node.inputs[0])
            node_tree.links.new(cmp_node.outputs[0], math_node.inputs[0])
        
        prev_color_node = mix_node
            
    node_tree.links.new(prev_color_node.outputs["Color"], group_output.inputs["Color"])
    
    return node_tree

def get_eye_highlight_node(r: ResourceResolver, forceCreate: bool = False) -> bpy.types.ShaderNodeGroup:
    if "EYE_HIGHLIGHT" in bpy.data.node_groups:
        if forceCreate:
            bpy.data.node_groups.remove(bpy.data.node_groups["EYE_HIGHLIGHT"])
        else:
            return bpy.data.node_groups["EYE_HIGHLIGHT"]
    
    node_tree = bpy.data.node_groups.new(name = "EYE_HIGHLIGHT", type = "ShaderNodeTree")
    nodes = node_tree.nodes
    nodes.clear()
    
    # Helper functions
    def create_math_node(input1, input2, operation: str, output = None, location: tuple[int,int] = (0,0)) -> bpy.types.ShaderNodeMath:
        node = nodes.new("ShaderNodeMath")
        node.operation = operation
        node.location = location
        
        if type(input1) is float:
            node.inputs[0].default_value = input1
        elif input2 is not None:
            node_tree.links.new(input1, node.inputs[0])
        
        if type(input2) is float:
            node.inputs[1].default_value = input2
        elif input2 is not None:
            node_tree.links.new(input2, node.inputs[1])
        
        if output is not None:
            node_tree.links.new(node.outputs[0], output)
        
        return node
    
    # Inputs/outputs
    group_input = nodes.new("NodeGroupInput")
    group_input.location = (-2400, 0)
    group_output = nodes.new("NodeGroupOutput")
    group_output.location = (400, 0)
    
    node_tree.inputs.new("NodeSocketFloat", "Iris UV Radius")
    node_tree.inputs.new("NodeSocketColor", "Iris Color")
    node_tree.inputs.new("NodeSocketFloat", "Iris Color Strength")
    node_tree.inputs.new("NodeSocketFloat", "Pupil Scale")
    
    node_tree.outputs.new("NodeSocketColor", "Base Color")
    
    # Nodes
    multiply_half_node = create_math_node(group_input.outputs["Iris UV Radius"], 0.5, "MULTIPLY", location = (-2200, -100))

    multiply_inverse_half_node = create_math_node(multiply_half_node.outputs[0], -0.5, "MULTIPLY", location = (-2000, -400))
    
    vec_add_half_node = nodes.new("ShaderNodeVectorMath")
    vec_add_half_node.location = (-1500, -400)
    vec_add_half_node.operation = "ADD"
    vec_add_half_node.inputs[1].default_value = (0.5, 0.5, 0)
    
    node_tree.links.new(multiply_inverse_half_node.outputs[0], vec_add_half_node.inputs[0])
    
    
    uv_map_node = nodes.new("ShaderNodeUVMap")
    uv_map_node.location = (-1500, 200)
    
    mapping_node = nodes.new("ShaderNodeMapping")
    mapping_node.location = (-1000, 0)
    mapping_node.vector_type = "TEXTURE"
    
    node_tree.links.new(uv_map_node.outputs["UV"], mapping_node.inputs["Vector"])
    node_tree.links.new(vec_add_half_node.outputs[0], mapping_node.inputs["Location"])
    node_tree.links.new(multiply_half_node.outputs[0], mapping_node.inputs["Scale"])
    
    
    iris_base_color_node = nodes.new("ShaderNodeTexImage")
    iris_base_color_node.location = (-500, -300)
    iris_base_color_node.image = bpy.data.images.load(bytes(r.resolveResourcePath(ResourceType.TEXTURE_2D, \
                                                                                  "EyeIrisBaseColor")), \
                                                            check_existing = True)
    node_tree.links.new(mapping_node.outputs["Vector"], iris_base_color_node.inputs["Vector"])
    
    
    iris_color_multiply_node = nodes.new("ShaderNodeMixRGB")
    iris_color_multiply_node.location = (0, -300)
    iris_color_multiply_node.blend_type = "MULTIPLY"
    
    node_tree.links.new(iris_base_color_node.outputs["Color"], iris_color_multiply_node.inputs["Color1"])
    node_tree.links.new(group_input.outputs["Iris Color"], iris_color_multiply_node.inputs["Color2"])
    node_tree.links.new(group_input.outputs["Iris Color Strength"], iris_color_multiply_node.inputs["Fac"])
    
    
    sclera_base_color_node = nodes.new("ShaderNodeTexImage")
    sclera_base_color_node.location = (-500, 200)
    sclera_base_color_node.image = bpy.data.images.load(bytes(r.resolveResourcePath(ResourceType.TEXTURE_2D, \
                                                                                    "EyeScleraBaseColor")), \
                                                              check_existing = True)
    
    cmp_half_node = create_math_node(multiply_half_node.outputs["Value"], 0.5, "MULTIPLY", location = (-1000, -400))
    
    distance_node = nodes.new("ShaderNodeVectorMath")
    distance_node.location = (-1000, -600)
    distance_node.operation = "DISTANCE"
    distance_node.inputs[1].default_value = (0.5, 0.5, 0)
    
    node_tree.links.new(uv_map_node.outputs["UV"], distance_node.inputs[0])
    
    
    cmp_node = create_math_node(distance_node.outputs["Value"], cmp_half_node.outputs["Value"], "LESS_THAN", location = (-500, -400))
    
    
    final_mix_node = nodes.new("ShaderNodeMixRGB")
    final_mix_node.location = (200, 0)
    final_mix_node.blend_type = "MIX"
    
    
    node_tree.links.new(cmp_node.outputs["Value"],                 final_mix_node.inputs["Fac"])
    node_tree.links.new(sclera_base_color_node.outputs["Color"],   final_mix_node.inputs["Color1"])
    node_tree.links.new(iris_color_multiply_node.outputs["Color"], final_mix_node.inputs["Color2"])
    node_tree.links.new(final_mix_node.outputs["Color"],           group_output.inputs["Base Color"])
    
    return node_tree

def setup_materials(r: ResourceResolver):
    
    
    eye_data = ""
    
    # Fore the recreation
    get_creation_mask_node(True)
    get_eye_highlight_node(r, True)
    
    def create_texture_node(prop: Property) -> bpy.types.ShaderNodeTexImage:
        node = nodes.new("ShaderNodeTexImage")
        if type(prop) is str:
            img_path = r.resolveResourcePath(ResourceType.TEXTURE_2D, prop)
        else:
            img_path = r.resolveResourcePath(prop.propertyType, prop.value)
        if img_path is not None:
            node.image = bpy.data.images.load(bytes(img_path), check_existing=True)
        return node
    
    def add_remap_nodes(propertyName: str, outputSocket, inputSocket, nodeLocation) -> None:
        if "SpecularMin" in p.properties or "SpecularMax" in p.properties:
            prop_min = p.properties["{0}Min".format(propertyName)].value if "{0}Min".format(propertyName) in p.properties else 0.0
            prop_max = p.properties["{0}Max".format(propertyName)].value if "{0}Max".format(propertyName) in p.properties else 1.0 
            
            remap_node = nodes.new("ShaderNodeMapRange")
            remap_node.location = nodeLocation
            remap_node.label = "Remap {0} values".format(propertyName)
            remap_node.inputs["To Min"].default_value = prop_min
            remap_node.inputs["To Max"].default_value = prop_max
            
            mat.node_tree.links.new(outputSocket, remap_node.inputs["Value"])
            mat.node_tree.links.new(remap_node.outputs["Result"], inputSocket)
        else:
            mat.node_tree.links.new(outputSocket, inputSocket)
        
    
    for name, mat in bpy.data.materials.items():
        print("Loading {0}".format(name))
        data = r.readResource(ResourceType.CHARA_MAT, name)
        
        # The FakeEyeHighLight material cannot be read for some reason, so when we encounter another material
        # with data about the eye stored, such as the Eye material, store it in here and use it later.
        
        if name.endswith("EyeFakeHighLight"):
            data = eye_data
        
        if data:
            p: PropertyFile = PropertyFile(data, r)
            p.build()
            
            # Debug: print property values of this material
            #for propName, propValue in p.properties.items():
                #print("    {0}: {1}".format(propName, repr(propValue)))
            
            if "Iris UV Radius" in p.properties:
                eye_data = data
            
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            nodes.clear()
            
            bsdf_node = nodes.new('ShaderNodeBsdfPrincipled')
            bsdf_node.location = (0,0)
            output_node = nodes.new('ShaderNodeOutputMaterial')
            output_node.location = (500,0)
                
            mat.node_tree.links.new(bsdf_node.outputs[0], output_node.inputs[0])
            
            if name.endswith("EyeFakeHighLight"):
                # Set up the eye material
                base_color_node = nodes.new("ShaderNodeGroup")
                base_color_node.location = (-200, 0)
                base_color_node.node_tree = get_eye_highlight_node(r)
                base_color_node.inputs["Iris UV Radius"].default_value = p.properties["Iris UV Radius"].value
                base_color_node.inputs["Iris Color"].default_value =  p.properties["CreationColor1"].value
                
                mat.node_tree.links.new(base_color_node.outputs["Base Color"], bsdf_node.inputs["Base Color"])
                
                normal_tex_node = create_texture_node("EYE_NORMALS")
                normal_tex_node.location = (-600, -400)
                
                normal_map_node = nodes.new("ShaderNodeNormalMap")
                normal_map_node.location = (-200, -400)
                
                mat.node_tree.links.new(normal_tex_node.outputs["Color"], normal_map_node.inputs["Color"])
                mat.node_tree.links.new(normal_map_node.outputs["Normal"], bsdf_node.inputs["Normal"])
            
            elif name.endswith("Eye"):
                # Set up the EyeLash material
                base_color_node = create_texture_node("FACE_eyelash_COLOR")
                base_color_node.location = (-600, 0)
                
                mix_node = nodes.new("ShaderNodeMixRGB")
                mix_node.location = (-200,0)
                mix_node.blend_type = "MULTIPLY"
                mix_node.inputs["Fac"].default_value = 1.0
                mix_node.inputs["Color2"].default_value = (0, 0, 0, 0)
                
                mat.node_tree.links.new(base_color_node.outputs["Color"], mix_node.inputs["Color1"])
                mat.node_tree.links.new(mix_node.outputs["Color"], bsdf_node.inputs["Base Color"])
                mat.node_tree.links.new(base_color_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])
                
            else:
                # Set up other materials
                if "Anisotropy" in p.properties:
                    bsdf_node.inputs["Anisotropic"].default_value = p.properties["Anisotropy"].value
                
                if "Metallic" in p.properties:
                    bsdf_node.inputs["Metallic"].default_value = p.properties["Metallic"].value
                    
                if "IoR" in p.properties:
                    bsdf_node.inputs["IOR"].default_value = p.properties["IoR"].value
                
                if "BaseColor" in p.properties:
                    base_color_node = create_texture_node(p.properties["BaseColor"])
                    
                    if "OpacityMax" in p.properties and "OpacityMin" in p.properties:
                        # Handle a custom alpha ramp if it is set
                        opacity_max = p.properties["OpacityMax"].value
                        opacity_min = p.properties["OpacityMin"].value
                        
                        opacity_ramp_node = nodes.new("ShaderNodeValToRGB")
                        opacity_ramp_node.location = (-900, -500)
                        
                        opacity_ramp_node.color_ramp.elements[0].color = (1, 1, 1, 1)
                        opacity_ramp_node.color_ramp.elements[0].alpha = opacity_min
                        opacity_ramp_node.color_ramp.elements[1].alpha = opacity_max
                        
                        if "OpacityMiddle" in p.properties and "OpacityMiddlePoint" in p.properties:
                            # Add a middle point
                            opacity_middle       = p.properties["OpacityMiddle"].value
                            opacity_middle_point = p.properties["OpacityMiddlePoint"].value
                            
                            middle_element = opacity_ramp_node.color_ramp.elements.new(opacity_middle_point)
                            middle_element.color = (1, 1, 1, 1)
                            middle_element.alpha = opacity_middle
                        
                        mat.node_tree.links.new(base_color_node.outputs["Alpha"],   opacity_ramp_node.inputs["Fac"])
                        mat.node_tree.links.new(opacity_ramp_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])
                    else:
                        mat.node_tree.links.new(base_color_node.outputs["Alpha"], bsdf_node.inputs["Alpha"])
                    
                    
                    if "CreationMask" in p.properties:
                        # Creates a group of nodes that replaces the color of the mask with another color
                        base_color_node.location = (-1500, -300)
                        creation_mask_texture_node = create_texture_node(p.properties["CreationMask"])
                        creation_mask_texture_node.label = "Creation Mask"
                        creation_mask_texture_node.location = (-1500, 0)
                        
                        creation_mask_node = nodes.new("ShaderNodeGroup")
                        creation_mask_node.location = (-600, 200)
                        creation_mask_node.node_tree = get_creation_mask_node()
                        
                        mat.node_tree.links.new(base_color_node.outputs["Color"], creation_mask_node.inputs["Base Color"])
                        mat.node_tree.links.new(creation_mask_texture_node.outputs["Color"], creation_mask_node.inputs["Creation Mask"])
                        mat.node_tree.links.new(creation_mask_texture_node.outputs["Alpha"], creation_mask_node.inputs["Creation Mask Alpha"])
                        
                        creation_valid_mask = p.properties["CreationValidMask"].value
                        
                        for i, valid in enumerate(creation_valid_mask):
                            if valid != 0.0:
                                creation_color_prop_name = "CreationColor{0}".format(i + 1)
                                if creation_color_prop_name in p.properties:
                                    color = p.properties[creation_color_prop_name].value
                                else:
                                    color = (0, 0, 0, 1)
                                creation_mask_node.inputs["Color {0}".format(i + 1)].default_value = color
                               
                        
                        base_color_link = mat.node_tree.links.new(creation_mask_node.outputs["Color"], bsdf_node.inputs["Base Color"])
                    else:
                        # If there is no creation mask, connect it directly to the bsdf node
                        base_color_node.location = (-1000, 0)
                        base_color_link = mat.node_tree.links.new(base_color_node.outputs["Color"], bsdf_node.inputs["Base Color"])
                
                if "NormalMap" in p.properties:
                    normal_tex_node = create_texture_node(p.properties["NormalMap"])
                    normal_tex_node.location = (-500, -600)
                    
                    normal_map_node = nodes.new("ShaderNodeNormalMap")
                    normal_map_node.location = (-250, -600)
                    
                    mat.node_tree.links.new(normal_tex_node.outputs["Color"], normal_map_node.inputs["Color"])
                    mat.node_tree.links.new(normal_map_node.outputs["Normal"], bsdf_node.inputs["Normal"])
                    
                if "ParameterMap" in p.properties:
                    # http://modderbase.com/showthread.php?tid=1878
                    # Red Channel: Specular
                    # Green Channel: Roughness
                    # Blue Channel: Metalness
                    # Alpha Channel: ???
                    param_map_node = create_texture_node(p.properties["ParameterMap"])
                    param_map_node.location = (-900, -250)
                    param_map_split_node = nodes.new("ShaderNodeSeparateRGB")
                    param_map_split_node.location = (-600, -200)
                    
                    mat.node_tree.links.new(param_map_node.outputs["Color"],   param_map_split_node.inputs["Image"]) 
                    add_remap_nodes("Specular",  param_map_split_node.outputs["R"], bsdf_node.inputs["Specular"],  (-400, -100))
                    add_remap_nodes("Roughness", param_map_split_node.outputs["G"], bsdf_node.inputs["Roughness"], (-200, -200))
                    mat.node_tree.links.new(param_map_split_node.outputs["B"], bsdf_node.inputs["Metallic"])
                    
                    mix_ao_node = nodes.new("ShaderNodeMixRGB")
                    mix_ao_node.blend_type = "MULTIPLY"
                    mix_ao_node.location = (-300, 200)
                    mix_ao_node.inputs["Fac"].default_value = 1.0
                    
                    #base_color_link.to_socket = mix_ao_node.inputs["Color1"]
                    mat.node_tree.links.new(base_color_link.from_socket,   mix_ao_node.inputs["Color1"])
                    mat.node_tree.links.new(param_map_node.outputs["Alpha"],   mix_ao_node.inputs["Color2"])
                    mat.node_tree.links.new(mix_ao_node.outputs["Color"], bsdf_node.inputs["Base Color"])
                
                # Some hard-coded material fixups until the material loading is done correclty
                if name.endswith("Eyebrow"):
                    # Patch some mistakes on the eyebrow material
                    creation_mask_texture_path = r.resolveResourcePath(ResourceType.TEXTURE_2D, "red_16x16")
                    creation_mask_texture_node.image = bpy.data.images.load(bytes(creation_mask_texture_path), check_existing=True)   
                    
                    param_mask_texture_path = r.resolveResourcePath(ResourceType.TEXTURE_2D, "black_16x16")
                    creation_mask_texture_node.image = bpy.data.images.load(bytes(param_mask_texture_path), check_existing=True)   
                elif name.endswith("Tear"):
                    base_color_texture_path = r.resolveResourcePath(ResourceType.TEXTURE_2D, "FACE_namida_COLOR")
                    base_color_node.image = bpy.data.images.load(bytes(param_mask_texture_path), check_existing=True)
                    
if __name__ == "__main__":
    r: ResourceResolver = ResourceResolver()
    setup_materials()