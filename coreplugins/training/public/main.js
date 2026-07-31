PluginsAPI.Map.willAddControls([
        'training/build/Training.js',
        'training/build/Training.css'
    ], function(args, Training){
    var tasks = [];
    var ids = {};

    for (var i = 0; i < args.tiles.length; i++){
        var task = args.tiles[i].meta.task;
        if (!ids[task.id]){
            tasks.push(task);
            ids[task.id] = true;
        }
    }

    if (tasks.length > 0){
        args.map.addControl(new Training({map: args.map, tasks: tasks, tiles: args.tiles}));
    }
});
