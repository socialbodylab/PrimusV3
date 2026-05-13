# Overview 
At this stage the control sofware has gotten fairly complex and needs a reorganization.
- Cues : the top level of combined looks
- Looks : Combination / manipulation of Clips
- Clips : Single output effect on a channel

# Clearer hierarchy between the components

## Top Level - Cues
### What are they
Cues are triggerable collections of looks that are targetted to specific devices. It allows different looks to be sent to differnt devices simultaneously.

### Cue UI
It should be presented as a digital version of a board that allows cue to be triggered live in the production
Large Text of Cue Controller at top
- It should take the full screen, hiding the devices panel. When on the Cue Controller tab all available devices on the network should be connected. 
- should provide a clear name in large with small notes of the Looks/devices. 
- should provide a small edit button to allow 
- Add cue button at the top that opens a view to add different looks 
- Looks should have previews similar to Clips library in the timeline view
- Create a default blackout look that can be easily added to a cue

## Phase one implementation
- Cue Controller is the live board view and hides the network Devices sidebar.
- Entering Cue Controller connects saved devices and sends controller blackout before show operation.
- Cues now support multiple assignments. Each assignment can trigger a Look to its own target mode, or act as a virtual blackout.
- Old single-Look cues are still accepted and normalized into assignments.
- The visible Cue Controller is only a manual grid of square cue buttons. There is no GO/NEXT transport, auto-follow setup, cue timeline, or output-ownership panel in this view.
- Clicking a cue square triggers it. The only control on a square is Edit; delete lives inside the editor.